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

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.core_aviation.domain import CustomerType
from sky_bridge_jet.modules.core_aviation.models import Customer
from sky_bridge_jet.modules.iam.domain import (
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
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
)

# Stable append-only security-audit event for a successful self-provisioning.
CUSTOMER_SELF_PROVISIONED_EVENT = "customer_self_provisioned"

# The Customer/Organization schema requires a display name. We use a neutral,
# non-sensitive placeholder — never a company name and never derived from the email —
# provisional until the Phase 9.1 customer-profile experience lets the owner set it.
PROVISIONAL_ACCOUNT_DISPLAY_NAME = "Personal account"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def provision_personal_customer(session: Session, user: User) -> Organization | None:
    """Provision a personal customer tenant for a just-verified user, atomically.

    MUST be called inside the email-verification transaction with the user row already
    locked. Returns the new CUSTOMER ``Organization``, or ``None`` when provisioning is
    skipped because a higher-precedence path applies:

    - the user is not ACTIVE (a suspended/disabled user never provisions);
    - the user already has an active organization membership;
    - a still-valid pending invitation exists for the user's email.
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
    AuditRepository(session).record(
        CUSTOMER_SELF_PROVISIONED_EVENT, user_id=user.id, organization_id=organization.id
    )
    return organization
