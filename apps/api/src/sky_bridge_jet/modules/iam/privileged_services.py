"""Trusted linking and OIDC-session orchestration for privileged staff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.modules.iam.domain import (
    AuthenticationError,
    MembershipStatus,
    OrganizationType,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import (
    ExternalIdentityLink,
    Organization,
    OrganizationMembership,
    PrivilegedAuthTransaction,
    User,
    UserSession,
)
from sky_bridge_jet.modules.iam.privileged_identity import (
    PrivilegedIdentityError,
    PrivilegedIdentityProvider,
    VerifiedIdentityAssertion,
    new_oidc_material,
)
from sky_bridge_jet.modules.iam.repositories import AuditRepository
from sky_bridge_jet.modules.iam.security import generate_token, hash_token


def _now() -> datetime:
    return datetime.now(UTC)


class PrivilegedIdentityService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.audit = AuditRepository(session)

    def create_transaction(self, provider: PrivilegedIdentityProvider) -> tuple[str, str]:
        state, nonce, verifier, challenge = new_oidc_material()
        with self.session.begin():
            self.session.add(
                PrivilegedAuthTransaction(
                    state_hash=hash_token(state),
                    nonce=nonce,
                    pkce_verifier=verifier,
                    return_path="/platform/pilot",
                    expires_at=_now() + timedelta(minutes=10),
                )
            )
        return provider.authorization_url(state=state, nonce=nonce, code_challenge=challenge), state

    def complete(
        self, *, provider: PrivilegedIdentityProvider, state: str, code: str
    ) -> tuple[UserSession, str, str, str]:
        # Consume correlation state in its own transaction before the provider call.
        # A failed exchange is therefore not replayable and no network I/O holds a DB lock.
        invalid_state = False
        with self.session.begin():
            transaction = self.session.scalars(
                select(PrivilegedAuthTransaction)
                .where(PrivilegedAuthTransaction.state_hash == hash_token(state))
                .with_for_update()
            ).first()
            if (
                transaction is None
                or transaction.consumed_at is not None
                or transaction.expires_at <= _now()
            ):
                self.audit.record("privileged_callback_failed", detail="STATE_MISMATCH")
                invalid_state = True
                nonce = verifier = return_path = ""
            else:
                transaction.consumed_at = _now()
                nonce = transaction.nonce
                verifier = transaction.pkce_verifier
                transaction.nonce = "consumed"
                transaction.pkce_verifier = "consumed"
                return_path = transaction.return_path
        if invalid_state:
            raise PrivilegedIdentityError("STATE_MISMATCH")
        try:
            assertion = provider.exchange_and_verify(code=code, nonce=nonce, pkce_verifier=verifier)
        except PrivilegedIdentityError as error:
            with self.session.begin():
                self.audit.record("privileged_callback_failed", detail=error.classification)
            raise
        try:
            with self.session.begin():
                user, link = self._resolve_assertion(assertion)
                raw_token = generate_token()
                csrf = generate_token()
                now = _now()
                absolute = now + timedelta(
                    seconds=self.settings.privileged_session_absolute_seconds
                )
                assurance = min(
                    absolute,
                    assertion.mfa_verified_at
                    + timedelta(seconds=self.settings.privileged_assurance_ttl_seconds),
                )
                record = UserSession(
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    csrf_token=csrf,
                    created_at=now,
                    expires_at=absolute,
                    last_seen_at=now,
                    identity_provider=assertion.provider,
                    external_identity_link_id=link.id,
                    provider_auth_time=assertion.auth_time,
                    mfa_verified_at=assertion.mfa_verified_at,
                    assurance_expires_at=assurance,
                    provider_session_reference=assertion.provider_session_reference,
                )
                self.session.add(record)
                self.session.flush()
                self.audit.record("privileged_mfa_login", user_id=user.id)
        except PrivilegedIdentityError as error:
            with self.session.begin():
                self.audit.record("privileged_callback_failed", detail=error.classification)
            raise
        return record, raw_token, csrf, return_path

    def _resolve_assertion(
        self, assertion: VerifiedIdentityAssertion
    ) -> tuple[User, ExternalIdentityLink]:
        link = self.session.scalars(
            select(ExternalIdentityLink).where(
                ExternalIdentityLink.issuer == assertion.issuer,
                ExternalIdentityLink.subject == assertion.subject,
                ExternalIdentityLink.revoked_at.is_(None),
            )
        ).first()
        if link is None:
            raise PrivilegedIdentityError("IDENTITY_NOT_LINKED")
        user = self.session.get(User, link.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise PrivilegedIdentityError("USER_DISABLED")
        platform_membership = self.session.scalars(
            select(OrganizationMembership)
            .join(Organization, Organization.id == OrganizationMembership.organization_id)
            .where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
                Organization.organization_type == OrganizationType.PLATFORM,
            )
        ).first()
        if platform_membership is None:
            raise PrivilegedIdentityError("PLATFORM_MEMBERSHIP_REQUIRED")
        return user, link

    def trusted_link(
        self,
        *,
        user_id: UUID,
        issuer: str,
        subject: str,
        actor_user_id: UUID | None,
        provider: str = "auth0",
    ) -> ExternalIdentityLink:
        """Bootstrap/admin-only service seam; deliberately has no public HTTP route."""
        try:
            with self.session.begin():
                user = self.session.get(User, user_id, with_for_update=True)
                if user is None or user.status is not UserStatus.ACTIVE:
                    raise AuthenticationError("Active staff user required")
                link = ExternalIdentityLink(
                    user_id=user_id,
                    provider=provider,
                    issuer=issuer,
                    subject=subject,
                    created_by_user_id=actor_user_id,
                )
                self.session.add(link)
                self.session.flush()
                self.audit.record("external_identity_link_created", user_id=user_id)
                return link
        except IntegrityError as error:
            raise AuthenticationError("External identity is already linked") from error


def privileged_assurance_valid(record: UserSession, settings: Settings) -> bool:
    now = _now()
    if (
        record.identity_provider not in {"auth0", "fake"}
        or record.external_identity_link_id is None
        or record.mfa_verified_at is None
        or record.assurance_expires_at is None
        or record.assurance_expires_at <= now
        or record.created_at + timedelta(seconds=settings.privileged_session_absolute_seconds)
        <= now
    ):
        return False
    last_seen = record.last_seen_at or record.created_at
    return last_seen + timedelta(seconds=settings.privileged_session_inactivity_seconds) > now
