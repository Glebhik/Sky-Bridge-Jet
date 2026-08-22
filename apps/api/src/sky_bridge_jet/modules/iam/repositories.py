from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.iam.domain import InvitationStatus, MembershipStatus
from sky_bridge_jet.modules.iam.models import (
    AuthAuditLog,
    EmailVerificationToken,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    PasswordResetToken,
    User,
    UserSession,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        return user

    def get(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_for_update(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id, with_for_update=True)

    def get_by_normalized_email(self, normalized_email: str) -> User | None:
        return self.session.scalars(
            select(User).where(User.normalized_email == normalized_email)
        ).first()


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        return organization

    def get(self, organization_id: UUID) -> Organization | None:
        return self.session.get(Organization, organization_id)


class MembershipRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, membership: OrganizationMembership) -> OrganizationMembership:
        self.session.add(membership)
        return membership

    def active_for_user(self, user_id: UUID) -> list[OrganizationMembership]:
        return list(
            self.session.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                )
            ).all()
        )

    def get_active(self, user_id: UUID, organization_id: UUID) -> OrganizationMembership | None:
        return self.session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()

    def get_for_update(self, membership_id: UUID) -> OrganizationMembership | None:
        return self.session.get(OrganizationMembership, membership_id, with_for_update=True)

    def list_active_for_org(self, organization_id: UUID) -> list[OrganizationMembership]:
        return list(
            self.session.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                )
            ).all()
        )

    def count_active_with_role(self, organization_id: UUID, role: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.role == role,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                )
            )
            or 0
        )


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        return user_session

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        return self.session.scalars(
            select(UserSession).where(UserSession.token_hash == token_hash)
        ).first()

    def get_for_update(self, session_id: UUID) -> UserSession | None:
        return self.session.get(UserSession, session_id, with_for_update=True)

    def active_for_user(self, user_id: UUID) -> list[UserSession]:
        now = _utc_now()
        return list(
            self.session.scalars(
                select(UserSession).where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
            ).all()
        )

    def revoke_all_for_user(self, user_id: UUID) -> int:
        revoked = 0
        for row in self.active_for_user(user_id):
            row.revoked_at = _utc_now()
            revoked += 1
        return revoked


class EmailVerificationTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token: EmailVerificationToken) -> EmailVerificationToken:
        self.session.add(token)
        return token

    def get_by_hash(self, token_hash: str) -> EmailVerificationToken | None:
        return self.session.scalars(
            select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        ).first()

    def consume_all_unconsumed_for_user(self, user_id: UUID, *, now: datetime) -> int:
        """Mark every still-unconsumed verification token for the user as consumed.

        Used when re-issuing a verification token so there is exactly one current
        verification path: any previously issued, still-unused token is invalidated in
        the same transaction before the replacement is added. Uses the existing
        ``consumed_at`` column, so no schema change is required. Returns the number of
        tokens invalidated.
        """
        result = cast(
            "CursorResult[Any]",
            self.session.execute(
                update(EmailVerificationToken)
                .where(
                    EmailVerificationToken.user_id == user_id,
                    EmailVerificationToken.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            ),
        )
        return result.rowcount or 0


class PasswordResetTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token: PasswordResetToken) -> PasswordResetToken:
        self.session.add(token)
        return token

    def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        return self.session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        ).first()


class InvitationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        self.session.add(invitation)
        return invitation

    def get_by_hash_for_update(self, token_hash: str) -> OrganizationInvitation | None:
        return self.session.scalars(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.token_hash == token_hash)
            .with_for_update()
        ).first()

    def list_for_org(self, organization_id: UUID) -> list[OrganizationInvitation]:
        return list(
            self.session.scalars(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.organization_id == organization_id
                )
            ).all()
        )

    def count_valid_pending_for_email(self, invited_email_normalized: str, *, now: datetime) -> int:
        """Count still-valid (PENDING and unexpired) invitations for an email.

        A positive count means the invitation path is authoritative and personal
        customer self-provisioning must be skipped (Phase 9.0.B B).
        """
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(OrganizationInvitation)
                .where(
                    OrganizationInvitation.invited_email_normalized == invited_email_normalized,
                    OrganizationInvitation.status == InvitationStatus.PENDING,
                    OrganizationInvitation.expires_at > now,
                )
            )
            or 0
        )


class AuditRepository:
    """Append-only. Callers pass only non-sensitive descriptors — never a token."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        event: str,
        *,
        user_id: UUID | None = None,
        organization_id: UUID | None = None,
        detail: str | None = None,
    ) -> AuthAuditLog:
        entry = AuthAuditLog(
            event=event, user_id=user_id, organization_id=organization_id, detail=detail
        )
        self.session.add(entry)
        return entry
