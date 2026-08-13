"""Identity, session, and organization services.

Transactions are explicit per command. Secrets (passwords, raw tokens) are handled
only long enough to hash them; the raw value is returned to the caller exactly once
and never persisted or logged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.modules.iam.authz import (
    MembershipContext,
    Principal,
    ResourceScope,
    authorize,
)
from sky_bridge_jet.modules.iam.domain import (
    ADMIN_ROLE_BY_ORG_TYPE,
    AuthenticationError,
    EmailAlreadyRegisteredError,
    InvalidTokenError,
    InvitationStatus,
    LastAdminError,
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    Permission,
    PrivilegeEscalationError,
    UserStatus,
    normalize_email,
    permissions_for_role,
    role_is_valid_for_org_type,
    validate_password,
)
from sky_bridge_jet.modules.iam.models import (
    EmailVerificationToken,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    PasswordResetToken,
    User,
    UserSession,
)
from sky_bridge_jet.modules.iam.repositories import (
    AuditRepository,
    EmailVerificationTokenRepository,
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    PasswordResetTokenRepository,
    SessionRepository,
    UserRepository,
)
from sky_bridge_jet.modules.iam.security import (
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)

# A precomputed Argon2 hash used to equalize timing when an email is unknown, so
# login does not leak account existence through response time.
_DUMMY_PASSWORD_HASH = hash_password("timing-equalization-not-a-real-secret")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def load_principal(session: Session, user: User, session_id: UUID) -> Principal:
    """Build the request principal from a user's active memberships and org links."""
    memberships = MembershipRepository(session).active_for_user(user.id)
    contexts: list[MembershipContext] = []
    org_repo = OrganizationRepository(session)
    for membership in memberships:
        org = org_repo.get(membership.organization_id)
        if org is None:
            continue
        contexts.append(
            MembershipContext(
                organization_id=org.id,
                organization_type=org.organization_type,
                role=membership.role,
                customer_id=org.customer_id,
                operator_id=org.operator_id,
            )
        )
    return Principal(
        user_id=user.id,
        session_id=session_id,
        status=user.status,
        memberships=tuple(contexts),
    )


class AuthService:
    """Registration, verification, login/session, and password recovery."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)
        self.sessions = SessionRepository(session)
        self.email_tokens = EmailVerificationTokenRepository(session)
        self.reset_tokens = PasswordResetTokenRepository(session)
        self.audit = AuditRepository(session)

    # -- Registration & verification ---------------------------------------
    def register(
        self, *, email: str, password: str, display_name: str | None = None
    ) -> tuple[User, str]:
        """Create a PENDING_VERIFICATION user; return the user and a raw verify token."""
        normalized = normalize_email(email)
        validate_password(password)
        try:
            with self.session.begin():
                if self.users.get_by_normalized_email(normalized) is not None:
                    raise EmailAlreadyRegisteredError("An account with this email already exists")
                user = self.users.add(
                    User(
                        email=email.strip(),
                        normalized_email=normalized,
                        display_name=display_name,
                        password_hash=hash_password(password),
                        status=UserStatus.PENDING_VERIFICATION,
                    )
                )
                self.session.flush()
                raw_token = self._issue_verification_token(user.id)
                self.audit.record("user_registered", user_id=user.id)
                return user, raw_token
        except IntegrityError as error:
            # A concurrent registration lost the unique-email race.
            raise EmailAlreadyRegisteredError(
                "An account with this email already exists"
            ) from error

    def _issue_verification_token(self, user_id: UUID) -> str:
        raw = generate_token()
        self.email_tokens.add(
            EmailVerificationToken(
                user_id=user_id,
                token_hash=hash_token(raw),
                expires_at=_utc_now()
                + timedelta(seconds=self.settings.email_verification_ttl_seconds),
            )
        )
        return raw

    def verify_email(self, raw_token: str) -> User:
        with self.session.begin():
            record = self.email_tokens.get_by_hash(hash_token(raw_token))
            if record is None or record.consumed_at is not None or record.expires_at < _utc_now():
                raise InvalidTokenError("The verification link is invalid or has expired")
            record.consumed_at = _utc_now()
            user = self.users.get_for_update(record.user_id)
            if user is None:
                raise InvalidTokenError("The verification link is invalid or has expired")
            if user.status is UserStatus.PENDING_VERIFICATION:
                user.status = UserStatus.ACTIVE
            user.email_verified_at = _utc_now()
            self.audit.record("email_verified", user_id=user.id)
            return user

    # -- Login / sessions --------------------------------------------------
    def login(self, *, email: str, password: str) -> tuple[UserSession, str, str]:
        """Authenticate and open a session. Enumeration- and timing-safe.

        Returns ``(session, raw_session_token, csrf_token)``. Any failure raises the
        same generic :class:`AuthenticationError`; response time is equalized by a
        dummy hash verification when the email is unknown.
        """
        normalized = normalize_email(email) if "@" in email else email.strip().lower()
        with self.session.begin():
            user = self.users.get_by_normalized_email(normalized)
            if user is None or user.password_hash is None:
                verify_password(_DUMMY_PASSWORD_HASH, password)  # equalize timing
                self.audit.record("login_failed", detail="unknown_or_passwordless")
                raise AuthenticationError("Invalid email or password")
            if not verify_password(user.password_hash, password):
                self.audit.record("login_failed", user_id=user.id)
                raise AuthenticationError("Invalid email or password")
            if user.status is not UserStatus.ACTIVE:
                self.audit.record("login_denied_status", user_id=user.id, detail=user.status.value)
                raise AuthenticationError("Invalid email or password")
            raw_token = generate_token()
            csrf = generate_token()
            user_session = self.sessions.add(
                UserSession(
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    csrf_token=csrf,
                    expires_at=_utc_now() + timedelta(seconds=self.settings.session_ttl_seconds),
                    last_seen_at=_utc_now(),
                )
            )
            user.last_login_at = _utc_now()
            self.session.flush()
            self.audit.record("login_succeeded", user_id=user.id)
            return user_session, raw_token, csrf

    def authenticate_session(self, raw_token: str) -> tuple[UserSession, User] | None:
        """Resolve a session token to (session, user) if valid; else None.

        Suspended/disabled users and expired/revoked sessions resolve to None, so a
        suspension immediately blocks existing sessions.
        """
        record = self.sessions.get_by_token_hash(hash_token(raw_token))
        if record is None or record.revoked_at is not None or record.expires_at < _utc_now():
            return None
        user = self.users.get(record.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            return None
        return record, user

    def touch_session(self, session_id: UUID) -> None:
        with self.session.begin():
            record = self.sessions.get_for_update(session_id)
            if record is not None:
                record.last_seen_at = _utc_now()

    def logout(self, session_id: UUID) -> None:
        with self.session.begin():
            record = self.sessions.get_for_update(session_id)
            if record is not None and record.revoked_at is None:
                record.revoked_at = _utc_now()
                self.audit.record("logout", user_id=record.user_id)

    def logout_all(self, user_id: UUID) -> int:
        with self.session.begin():
            count = self.sessions.revoke_all_for_user(user_id)
            self.audit.record("sessions_revoked_all", user_id=user_id, detail=f"count={count}")
            return count

    # -- Password reset ----------------------------------------------------
    def request_password_reset(self, email: str) -> str | None:
        """Create a reset token if the account exists. Public behavior is uniform.

        Returns the raw token when a reset was issued (for the notification boundary)
        and ``None`` otherwise; the HTTP layer returns the same response either way,
        so the endpoint never reveals whether an email is registered.
        """
        try:
            normalized = normalize_email(email)
        except Exception:
            return None
        with self.session.begin():
            user = self.users.get_by_normalized_email(normalized)
            if user is None or user.status is UserStatus.DISABLED:
                return None
            raw = generate_token()
            self.reset_tokens.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(raw),
                    expires_at=_utc_now()
                    + timedelta(seconds=self.settings.password_reset_ttl_seconds),
                )
            )
            self.audit.record("password_reset_requested", user_id=user.id)
            return raw

    def reset_password(self, raw_token: str, new_password: str) -> User:
        validate_password(new_password)
        with self.session.begin():
            record = self.reset_tokens.get_by_hash(hash_token(raw_token))
            if record is None or record.consumed_at is not None or record.expires_at < _utc_now():
                raise InvalidTokenError("The reset link is invalid or has expired")
            record.consumed_at = _utc_now()
            user = self.users.get_for_update(record.user_id)
            if user is None:
                raise InvalidTokenError("The reset link is invalid or has expired")
            user.password_hash = hash_password(new_password)
            if user.status is UserStatus.PENDING_VERIFICATION:
                # Completing a reset also proves email control.
                user.status = UserStatus.ACTIVE
                user.email_verified_at = _utc_now()
            # Reset invalidates all existing sessions.
            self.sessions.revoke_all_for_user(user.id)
            self.audit.record("password_reset_completed", user_id=user.id)
            return user

    # -- Administration ----------------------------------------------------
    def set_user_status(self, user_id: UUID, status: UserStatus) -> User:
        with self.session.begin():
            user = self.users.get_for_update(user_id)
            if user is None:
                raise InvalidTokenError("User not found")
            user.status = status
            if status in {UserStatus.SUSPENDED, UserStatus.DISABLED}:
                self.sessions.revoke_all_for_user(user.id)
            self.audit.record("user_status_changed", user_id=user.id, detail=status.value)
            return user


class OrganizationService:
    """Organization creation, membership, invitations, and role administration."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.orgs = OrganizationRepository(session)
        self.memberships = MembershipRepository(session)
        self.invitations = InvitationRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditRepository(session)

    # -- Creation (admin / bootstrap) --------------------------------------
    def create_organization(
        self,
        *,
        organization_type: OrganizationType,
        display_name: str,
        customer_id: UUID | None = None,
        operator_id: UUID | None = None,
        owner_user_id: UUID | None = None,
        owner_role: OrganizationRole | None = None,
    ) -> Organization:
        with self.session.begin():
            org = self._create_org_in_tx(
                organization_type=organization_type,
                display_name=display_name,
                customer_id=customer_id,
                operator_id=operator_id,
            )
            if owner_user_id is not None:
                role = owner_role or ADMIN_ROLE_BY_ORG_TYPE[organization_type]
                self._add_membership_in_tx(owner_user_id, org.id, role)
            return org

    def _create_org_in_tx(
        self,
        *,
        organization_type: OrganizationType,
        display_name: str,
        customer_id: UUID | None,
        operator_id: UUID | None,
    ) -> Organization:
        org = self.orgs.add(
            Organization(
                organization_type=organization_type,
                display_name=display_name,
                customer_id=customer_id,
                operator_id=operator_id,
            )
        )
        self.session.flush()
        self.audit.record(
            "organization_created", organization_id=org.id, detail=organization_type.value
        )
        return org

    def _add_membership_in_tx(
        self, user_id: UUID, organization_id: UUID, role: OrganizationRole
    ) -> OrganizationMembership:
        membership = self.memberships.add(
            OrganizationMembership(user_id=user_id, organization_id=organization_id, role=role)
        )
        self.session.flush()
        self.audit.record(
            "membership_created",
            user_id=user_id,
            organization_id=organization_id,
            detail=f"role={role.value}",
        )
        return membership

    # -- Invitations -------------------------------------------------------
    def invite(
        self,
        actor: Principal,
        *,
        organization_id: UUID,
        email: str,
        role: OrganizationRole,
    ) -> tuple[OrganizationInvitation, str]:
        normalized = normalize_email(email)
        with self.session.begin():
            org = self.orgs.get(organization_id)
            if org is None:
                raise InvalidTokenError("Organization not found")
            self._require_membership_admin(actor, org)
            if not role_is_valid_for_org_type(role, org.organization_type):
                raise PrivilegeEscalationError("That role is not valid for this organization")
            self._deny_escalation(actor, org, role)
            raw = generate_token()
            invitation = self.invitations.add(
                OrganizationInvitation(
                    organization_id=org.id,
                    invited_email_normalized=normalized,
                    role=role,
                    token_hash=hash_token(raw),
                    invited_by_user_id=actor.user_id,
                    status=InvitationStatus.PENDING,
                    expires_at=_utc_now() + timedelta(seconds=self.settings.invitation_ttl_seconds),
                )
            )
            self.session.flush()
            self.audit.record(
                "membership_invited",
                user_id=actor.user_id,
                organization_id=org.id,
                detail=f"role={role.value}",
            )
            return invitation, raw

    def accept_invitation(self, user_id: UUID, raw_token: str) -> OrganizationMembership:
        with self.session.begin():
            user = self.users.get(user_id)
            if user is None:
                raise InvalidTokenError("The invitation is invalid or has expired")
            invitation = self.invitations.get_by_hash_for_update(hash_token(raw_token))
            if (
                invitation is None
                or invitation.status is not InvitationStatus.PENDING
                or invitation.expires_at < _utc_now()
            ):
                raise InvalidTokenError("The invitation is invalid or has expired")
            if invitation.invited_email_normalized != user.normalized_email:
                # Bound to the invited identity; do not reveal which org it targets.
                raise InvalidTokenError("The invitation is invalid or has expired")
            if self.memberships.get_active(user.id, invitation.organization_id) is not None:
                invitation.status = InvitationStatus.ACCEPTED
                invitation.accepted_at = _utc_now()
                raise LastAdminError("You are already a member of this organization")
            membership = self._add_membership_in_tx(
                user.id, invitation.organization_id, invitation.role
            )
            invitation.status = InvitationStatus.ACCEPTED
            invitation.accepted_at = _utc_now()
            self.audit.record(
                "membership_accepted",
                user_id=user.id,
                organization_id=invitation.organization_id,
                detail=f"role={invitation.role.value}",
            )
            return membership

    # -- Member administration --------------------------------------------
    def list_members(self, actor: Principal, organization_id: UUID) -> list[OrganizationMembership]:
        org = self.orgs.get(organization_id)
        if org is None:
            raise InvalidTokenError("Organization not found")
        self._require_membership_admin(actor, org)
        return self.memberships.list_active_for_org(organization_id)

    def change_role(
        self, actor: Principal, *, membership_id: UUID, new_role: OrganizationRole
    ) -> OrganizationMembership:
        with self.session.begin():
            membership = self.memberships.get_for_update(membership_id)
            if membership is None or membership.status is not MembershipStatus.ACTIVE:
                raise InvalidTokenError("Membership not found")
            org = self.orgs.get(membership.organization_id)
            if org is None:
                raise InvalidTokenError("Organization not found")
            self._require_membership_admin(actor, org)
            if not role_is_valid_for_org_type(new_role, org.organization_type):
                raise PrivilegeEscalationError("That role is not valid for this organization")
            self._deny_escalation(actor, org, new_role)
            # Last-admin protection: do not demote the final active admin.
            admin_role = ADMIN_ROLE_BY_ORG_TYPE[org.organization_type]
            if membership.role is admin_role and new_role is not admin_role:
                self._guard_last_admin(org, membership)
            membership.role = new_role
            self.audit.record(
                "membership_role_changed",
                user_id=membership.user_id,
                organization_id=org.id,
                detail=f"role={new_role.value}",
            )
            return membership

    def revoke_membership(self, actor: Principal, *, membership_id: UUID) -> OrganizationMembership:
        with self.session.begin():
            membership = self.memberships.get_for_update(membership_id)
            if membership is None or membership.status is not MembershipStatus.ACTIVE:
                raise InvalidTokenError("Membership not found")
            org = self.orgs.get(membership.organization_id)
            if org is None:
                raise InvalidTokenError("Organization not found")
            self._require_membership_admin(actor, org)
            admin_role = ADMIN_ROLE_BY_ORG_TYPE[org.organization_type]
            if membership.role is admin_role:
                self._guard_last_admin(org, membership)
            membership.status = MembershipStatus.REVOKED
            membership.revoked_at = _utc_now()
            self.audit.record(
                "membership_revoked",
                user_id=membership.user_id,
                organization_id=org.id,
                detail=f"role={membership.role.value}",
            )
            return membership

    # -- Policy helpers ----------------------------------------------------
    def _require_membership_admin(self, actor: Principal, org: Organization) -> None:
        """Actor must administer *this* organization (or be a platform admin)."""
        scope: ResourceScope
        if org.organization_type is OrganizationType.CUSTOMER and org.customer_id is not None:
            scope = ResourceScope.customer(org.customer_id)
        elif org.organization_type is OrganizationType.OPERATOR and org.operator_id is not None:
            scope = ResourceScope.operator(org.operator_id)
        else:
            scope = ResourceScope.global_()
        # Platform admins hold ADMIN_ORGANIZATIONS_MANAGE; org owners hold
        # ORG_MEMBERSHIP_MANAGE for their own tenant. Either authorizes.
        from sky_bridge_jet.modules.iam.authz import is_authorized

        if is_authorized(actor, Permission.ADMIN_ORGANIZATIONS_MANAGE, ResourceScope.global_()):
            return
        authorize(actor, Permission.ORG_MEMBERSHIP_MANAGE, scope)

    def _deny_escalation(self, actor: Principal, org: Organization, role: OrganizationRole) -> None:
        """A non-platform admin may not grant a role beyond their own permissions."""
        from sky_bridge_jet.modules.iam.authz import is_authorized

        if is_authorized(actor, Permission.ADMIN_ORGANIZATIONS_MANAGE, ResourceScope.global_()):
            return  # platform admin may assign any org-valid role
        granted = permissions_for_role(role)
        if not granted <= actor.all_permissions():
            raise PrivilegeEscalationError(
                "You cannot grant a role with more privileges than your own"
            )

    def _guard_last_admin(self, org: Organization, membership: OrganizationMembership) -> None:
        admin_role = ADMIN_ROLE_BY_ORG_TYPE[org.organization_type]
        remaining = self.memberships.count_active_with_role(org.id, admin_role.value)
        # `membership` is still ACTIVE in this transaction, so a count of 1 means it
        # is the last admin.
        if remaining <= 1:
            raise LastAdminError("This organization must keep at least one active administrator")


def bootstrap_product_owner(
    session: Session, *, email: str, password: str, display_name: str | None = None
) -> tuple[User, Organization]:
    """Create the first PRODUCT_OWNER and the platform organization.

    Idempotent-safe: refuses if any active PRODUCT_OWNER already exists, so the
    bootstrap cannot be used to mint additional superusers. Intended to be invoked
    from a one-time CLI, never an unauthenticated HTTP endpoint.
    """
    from sky_bridge_jet.modules.iam.models import AuthAuditLog

    normalized = normalize_email(email)
    validate_password(password)
    with session.begin():
        existing_owner = (
            session.query(OrganizationMembership)
            .filter(
                OrganizationMembership.role == OrganizationRole.PRODUCT_OWNER,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .first()
        )
        if existing_owner is not None:
            raise LastAdminError("A product owner already exists; bootstrap is disabled")
        user = session.query(User).filter(User.normalized_email == normalized).first()
        if user is None:
            user = User(
                email=email.strip(),
                normalized_email=normalized,
                display_name=display_name,
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
                email_verified_at=_utc_now(),
            )
            session.add(user)
            session.flush()
        else:
            user.status = UserStatus.ACTIVE
        org = Organization(
            organization_type=OrganizationType.PLATFORM,
            display_name="Sky Bridge Jet",
        )
        session.add(org)
        session.flush()
        session.add(
            OrganizationMembership(
                user_id=user.id,
                organization_id=org.id,
                role=OrganizationRole.PRODUCT_OWNER,
            )
        )
        session.add(
            AuthAuditLog(
                event="product_owner_bootstrapped",
                user_id=user.id,
                organization_id=org.id,
            )
        )
        session.flush()
        return user, org


__all__ = [
    "AuthService",
    "OrganizationService",
    "bootstrap_product_owner",
    "load_principal",
]
