"""Customer self-provisioning (Phase 9.0.B, ADR-044).

After a self-registering individual verifies their email, a personal customer tenant
is created **atomically inside the verification transaction**: one ``Customer``, one
CUSTOMER ``Organization`` linked to it, and one active ``CUSTOMER_OWNER``
``OrganizationMembership`` for the verified user, plus one append-only audit record.

The client supplies no identifiers or role — everything here is server-controlled.
Provisioning is skipped (returns ``None``) when the invitation path or an existing
active membership is authoritative, so an invited operator/platform/family-office user
never receives an unintended personal customer tenant. Because the caller has already
locked the user row and consumed the single-use verification token, concurrent or
repeated verification produces at most one tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.core_aviation.domain import CustomerType
from sky_bridge_jet.modules.core_aviation.models import Customer
from sky_bridge_jet.modules.iam.domain import (
    AccountAlreadyProvisionedError,
    AccountRecoveryIneligibleError,
    AuthenticationError,
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    PendingInvitationExistsError,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import (
    Organization,
    OrganizationMembership,
    User,
)
from sky_bridge_jet.modules.iam.repositories import (
    AuditRepository,
    InvitationRepository,
    MembershipRepository,
    UserRepository,
)

# Stable append-only security-audit event for a successful verification-time
# self-provisioning. Its historical semantics are preserved and never rewritten.
CUSTOMER_SELF_PROVISIONED_EVENT = "customer_self_provisioned"
# Stable append-only event for an authenticated self-service account recovery
# (Phase 9.1.A, ADR-047). Distinct from the verification-time event above so the
# audit trail separates the two provisioning paths.
CUSTOMER_ACCOUNT_RECOVERED_EVENT = "customer_account_recovered"

# The Customer/Organization schema requires a display name. We use a neutral,
# non-sensitive placeholder — never a company name and never derived from the email —
# provisional until the Phase 9.1 customer-profile experience lets the owner set it.
PROVISIONAL_ACCOUNT_DISPLAY_NAME = "Personal account"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def provision_personal_customer(
    session: Session,
    user: User,
    *,
    event: str = CUSTOMER_SELF_PROVISIONED_EVENT,
) -> Organization | None:
    """Provision a personal customer tenant for a user, atomically.

    MUST be called inside a transaction with the user row already locked. Returns the
    new CUSTOMER ``Organization``, or ``None`` when provisioning is skipped because a
    higher-precedence path applies:

    - the user is not ACTIVE (a suspended/disabled user never provisions);
    - the user already has an active organization membership;
    - a still-valid pending invitation exists for the user's email.

    ``event`` is the append-only audit event recorded on a successful new provisioning;
    it distinguishes verification-time self-provisioning from authenticated recovery.
    The eligibility guards are identical either way — the single provisioning path.
    """
    if user.status is not UserStatus.ACTIVE:
        return None
    if MembershipRepository(session).active_for_user(user.id):
        return None
    if (
        InvitationRepository(session).count_valid_pending_for_email(
            user.normalized_email, now=_utc_now()
        )
        > 0
    ):
        return None

    customer = Customer(
        customer_type=CustomerType.INDIVIDUAL,
        display_name=PROVISIONAL_ACCOUNT_DISPLAY_NAME,
        primary_email=user.email,
    )
    session.add(customer)
    session.flush()

    organization = Organization(
        organization_type=OrganizationType.CUSTOMER,
        display_name=PROVISIONAL_ACCOUNT_DISPLAY_NAME,
        customer_id=customer.id,
    )
    session.add(organization)
    session.flush()

    session.add(
        OrganizationMembership(
            user_id=user.id,
            organization_id=organization.id,
            role=OrganizationRole.CUSTOMER_OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )
    session.flush()

    # Safe metadata only: acting user and the new organization id — never tokens/PII.
    AuditRepository(session).record(event, user_id=user.id, organization_id=organization.id)
    return organization


def recover_personal_customer(session: Session, user_id: UUID) -> Organization:
    """Authenticated self-service recovery of a personal customer tenant (ADR-047).

    Opens one transaction and **locks the canonical user row first**, so concurrent or
    repeated recovery for the same user serialize on that lock and produce at most one
    tenant. Eligibility is classified into safe HTTP outcomes:

    - user missing → 401 (the session references an absent user);
    - user not ACTIVE (suspended/disabled/unverified) → 403;
    - an active membership already exists → 409;
    - a still-valid pending invitation exists → 409 (accept it first);
    - otherwise the single provisioning path runs and audits
      ``customer_account_recovered``.

    All of it — the Customer, Organization, Membership, and the audit record — commits
    together or rolls back together; a provisioning or audit failure leaves no partial
    tenant. The caller supplies no ownership identifiers; identity is the locked row.
    """
    with session.begin():
        user = UserRepository(session).get_for_update(user_id)
        if user is None:
            raise AuthenticationError("Authentication is required")
        if user.status is not UserStatus.ACTIVE:
            raise AccountRecoveryIneligibleError("This account is not eligible for recovery")
        if MembershipRepository(session).active_for_user(user.id):
            raise AccountAlreadyProvisionedError("This account already has an organization")
        if (
            InvitationRepository(session).count_valid_pending_for_email(
                user.normalized_email, now=_utc_now()
            )
            > 0
        ):
            raise PendingInvitationExistsError("A pending invitation must be accepted first")
        organization = provision_personal_customer(
            session, user, event=CUSTOMER_ACCOUNT_RECOVERED_EVENT
        )
        if organization is None:
            # Defensive: a race resolved the tenant between our checks and the guarded
            # provisioning. Report the same safe conflict rather than a partial success.
            raise AccountAlreadyProvisionedError("This account already has an organization")
        return organization
