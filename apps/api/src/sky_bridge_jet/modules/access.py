"""Customer-chain resource authorization (Phase 9.0.A-1).

This is the enforcement *seam* that closes the Phase 8 authorization debt for the
customer chain. It reuses the Phase 8 primitives — ``Principal``, ``ResourceScope``,
``is_authorized`` — and adds only two things:

1. **Active CUSTOMER-organization resolution** — which customer a principal is
   acting as, validated server-side against their memberships (never trusted from
   the client).
2. **Ownership resolution + a deny-by-default decision** mapping to the approved
   401/403/404/409 policy, with cross-tenant existence concealed as 404.

Ownership (``trip.customer_id``, ``passenger.customer_id``, booking→trip→customer,
payment→booking→trip→customer) is **immutable**, so resolving it on the request
session — then rolling back before a mutating service opens its own transaction — is
both race-free and consistent (ADR-040 / D5). Resolvers use the request session so
tests that override ``get_db`` and the operation's own consistency boundary are
honored.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError
from sky_bridge_jet.modules.core_aviation.models import Customer, Passenger, TripRequest
from sky_bridge_jet.modules.iam.authz import (
    MembershipContext,
    Principal,
    ResourceScope,
    is_authorized,
)
from sky_bridge_jet.modules.iam.domain import (
    AuthorizationError,
    OrganizationType,
    Permission,
)
from sky_bridge_jet.modules.iam.repositories import AuditRepository
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.payments.models import Payment

# Callback the customer-chain write services invoke inside their own transaction, so
# a platform-exception audit record commits atomically with (or rolls back with) the
# mutation. Type alias kept local to avoid coupling the domain services to IAM.
AuditHook = Callable[[Session], None]

# Stable, append-only security-audit event for a successful privileged platform
# exception exercised through the customer-authorization seam (ADR-040).
PLATFORM_EXCEPTION_EVENT = "platform_authorization_exception"


# --------------------------------------------------------------------------- #
# Principal introspection (pure)
# --------------------------------------------------------------------------- #
def _customer_memberships(principal: Principal) -> list[MembershipContext]:
    return [
        m
        for m in principal.memberships
        if m.organization_type is OrganizationType.CUSTOMER and m.customer_id is not None
    ]


def has_platform_permission(principal: Principal, permission: Permission) -> bool:
    """True if a PLATFORM membership grants the permission (cross-tenant viewer)."""
    return any(
        m.organization_type is OrganizationType.PLATFORM and permission in m.permissions
        for m in principal.memberships
    )


def _sees_customer_tenant(principal: Principal, customer_id: UUID) -> bool:
    """Whether the principal may even know the customer tenant exists.

    True for a member of that customer organization or any platform member. Used to
    choose 403 (visible, unauthorized) vs 404 (concealed cross-tenant).
    """
    if any(m.customer_id == customer_id for m in _customer_memberships(principal)):
        return True
    return any(m.organization_type is OrganizationType.PLATFORM for m in principal.memberships)


def active_customer_id(principal: Principal, requested_organization_id: UUID | None) -> UUID:
    """Resolve and validate the acting customer for a customer write.

    - one eligible CUSTOMER org → auto-selected;
    - multiple → an explicit, membership-validated ``X-Organization-Id`` is required;
    - the org must be an active CUSTOMER membership of the principal;
    - platform/operator principals have no customer context here (use the platform
      exception path in :func:`resolve_write_customer`).
    """
    eligible = _customer_memberships(principal)
    if requested_organization_id is not None:
        match = next((m for m in eligible if m.organization_id == requested_organization_id), None)
        if match is None or match.customer_id is None:
            # Do not disclose whether the org exists or is merely non-customer.
            raise AuthorizationError("Invalid active organization for this action")
        return match.customer_id
    if len(eligible) == 1:
        assert eligible[0].customer_id is not None
        return eligible[0].customer_id
    if not eligible:
        raise AuthorizationError("No customer organization context for this action")
    raise AuthorizationError("Multiple customer organizations; specify the active organization")


# --------------------------------------------------------------------------- #
# Decision (pure) — deny-by-default, 403 vs 404
# --------------------------------------------------------------------------- #
def require_customer_access(
    principal: Principal, permission: Permission, owner_customer_id: UUID | None
) -> None:
    """Enforce read/action access to a customer-owned resource.

    - ``owner_customer_id is None`` (resource absent) → 404;
    - authorized (owning customer, or platform with the permission) → allow;
    - visible tenant but lacking the permission → 403;
    - otherwise (cross-tenant / no visibility) → 404 (existence concealed).
    """
    if owner_customer_id is None:
        raise ResourceNotFoundError("Resource was not found")
    if is_authorized(principal, permission, ResourceScope.customer(owner_customer_id)):
        return
    if _sees_customer_tenant(principal, owner_customer_id):
        raise AuthorizationError("You are not permitted to perform this action")
    raise ResourceNotFoundError("Resource was not found")


def require_confidential_read(
    principal: Principal, permission: Permission, owner_customer_id: UUID | None
) -> None:
    """Enforce a read whose existing response still leaks confidential fields.

    Applies to offers/bookings/payments reads whose response exposes
    ``operator_amount_minor`` / ``platform_fee_minor``. Until the approved
    customer-safe projection lands in Phase 9.0.B, only a platform viewer (holding
    the permission cross-tenant) receives the full response. An owning customer is
    temporarily denied with 403 (visible context, no safe projection yet); any other
    principal, or a cross-tenant probe, receives 404 so existence is concealed.
    """
    if owner_customer_id is None:
        raise ResourceNotFoundError("Resource was not found")
    if has_platform_permission(principal, permission):
        return
    if _sees_customer_tenant(principal, owner_customer_id):
        # Owning customer: allowed to know it exists, but the full response is unsafe.
        raise AuthorizationError("A customer-safe view of this resource is not yet available")
    raise ResourceNotFoundError("Resource was not found")


def resolve_write_customer(
    session: Session,
    principal: Principal,
    *,
    body_customer_id: UUID | None,
    requested_organization_id: UUID | None,
) -> UUID:
    """Authoritative customer for a create/write, deriving ownership server-side.

    A customer principal acts within its validated active CUSTOMER organization; a
    body-supplied ``customer_id`` may only confirm that same tenant (a mismatch is
    concealed as 404). A platform principal holding ``customer.write`` may act for an
    explicit existing customer (the audited platform exception).
    """
    if _customer_memberships(principal):
        derived = active_customer_id(principal, requested_organization_id)
        if not is_authorized(principal, Permission.CUSTOMER_WRITE, ResourceScope.customer(derived)):
            raise AuthorizationError("You are not permitted to perform this action")
        if body_customer_id is not None and body_customer_id != derived:
            # Never act on, or confirm the existence of, another tenant.
            raise ResourceNotFoundError("Customer was not found")
        return derived
    # Platform exception: a platform principal with customer.write may act for an
    # explicit, existing customer. Never invent a customer id.
    if body_customer_id is not None and is_authorized(
        principal, Permission.CUSTOMER_WRITE, ResourceScope.customer(body_customer_id)
    ):
        if not customer_exists(session, body_customer_id):
            raise ResourceNotFoundError("Customer was not found")
        return body_customer_id
    raise AuthorizationError("You are not permitted to perform this action")


# --------------------------------------------------------------------------- #
# Ownership resolvers (read on the request session; immutable ownership)
# --------------------------------------------------------------------------- #
def customer_exists(session: Session, customer_id: UUID) -> bool:
    return session.get(Customer, customer_id) is not None


def owner_of_passenger(session: Session, passenger_id: UUID) -> UUID | None:
    return session.scalar(select(Passenger.customer_id).where(Passenger.id == passenger_id))


def owner_of_trip(session: Session, trip_request_id: UUID) -> UUID | None:
    return session.scalar(select(TripRequest.customer_id).where(TripRequest.id == trip_request_id))


def owner_of_offer(session: Session, offer_id: UUID) -> UUID | None:
    return session.scalar(
        select(TripRequest.customer_id)
        .join(OperatorOffer, OperatorOffer.trip_request_id == TripRequest.id)
        .where(OperatorOffer.id == offer_id)
    )


def owner_of_booking(session: Session, booking_id: UUID) -> UUID | None:
    return session.scalar(
        select(TripRequest.customer_id)
        .join(Booking, Booking.trip_request_id == TripRequest.id)
        .where(Booking.id == booking_id)
    )


def owner_of_payment(session: Session, payment_id: UUID) -> UUID | None:
    return session.scalar(
        select(TripRequest.customer_id)
        .join(Booking, Booking.trip_request_id == TripRequest.id)
        .join(Payment, Payment.booking_id == Booking.id)
        .where(Payment.id == payment_id)
    )


def owner_customer_of_booking_by_trip(session: Session, trip_request_id: UUID) -> UUID | None:
    """Customer owner used by the trip→booking read (same as trip owner)."""
    return owner_of_trip(session, trip_request_id)


# --------------------------------------------------------------------------- #
# Platform-exception security auditing (H1, ADR-040)
# --------------------------------------------------------------------------- #
# A privileged "platform exception" is a successful access to a customer-owned
# resource by a PLATFORM principal that is not a member of the owning customer
# organization (i.e. a cross-tenant/arbitrary-tenant action authorized by a platform
# role, not by customer ownership). Every such success is recorded once, append-only,
# in the existing Phase 8 ``auth_audit_log`` — never an ordinary customer acting in
# its own tenant, and never a denied attempt.


def _acting_platform_org(principal: Principal) -> UUID | None:
    for membership in principal.memberships:
        if membership.organization_type is OrganizationType.PLATFORM:
            return membership.organization_id
    return None


def is_platform_exception(principal: Principal, owner_customer_id: UUID | None) -> bool:
    """True when access to ``owner_customer_id`` succeeds via a platform role rather
    than customer ownership."""
    if owner_customer_id is None:
        return False
    owns = any(m.customer_id == owner_customer_id for m in _customer_memberships(principal))
    return not owns and _acting_platform_org(principal) is not None


def _exception_detail(
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    correlation_id: str | None,
) -> str:
    # Safe metadata only: normalized action/route id, permission, resource type and an
    # opaque identifier. Never card/financial splits, tokens, PII, or request bodies.
    detail = (
        f"action={action} resource={resource_type}:{resource_reference} "
        f"permission={permission.value} result=allowed"
    )
    if correlation_id:
        detail = f"{detail} correlation={correlation_id}"
    return detail[:300]


def platform_exception_hook(
    principal: Principal,
    *,
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    owner_customer_id: UUID | None,
    correlation_id: str | None = None,
) -> AuditHook | None:
    """Return an append-only audit hook iff this access is a platform exception.

    The hook is invoked *inside* the write service's transaction (via ``on_commit``)
    so the audit record commits atomically with the mutation and rolls back with it —
    a failed mutation never leaves a misleading successful-action record.
    """
    if not is_platform_exception(principal, owner_customer_id):
        return None
    user_id = principal.user_id
    org_id = _acting_platform_org(principal)
    detail = _exception_detail(
        permission, action, resource_type, resource_reference, correlation_id
    )

    def _hook(session: Session) -> None:
        AuditRepository(session).record(
            PLATFORM_EXCEPTION_EVENT, user_id=user_id, organization_id=org_id, detail=detail
        )

    return _hook


def platform_admin_hook(
    principal: Principal,
    *,
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    correlation_id: str | None = None,
) -> AuditHook:
    """An unconditional platform-exception audit hook for a route already gated to a
    platform-admin permission (e.g. platform-controlled Customer creation), where no
    owning customer exists yet to compare against."""
    user_id = principal.user_id
    org_id = _acting_platform_org(principal)
    detail = _exception_detail(
        permission, action, resource_type, resource_reference, correlation_id
    )

    def _hook(session: Session) -> None:
        AuditRepository(session).record(
            PLATFORM_EXCEPTION_EVENT, user_id=user_id, organization_id=org_id, detail=detail
        )

    return _hook


def audit_platform_read(
    session: Session,
    principal: Principal,
    *,
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    owner_customer_id: UUID | None,
    correlation_id: str | None = None,
) -> None:
    """Persist a platform-exception audit for a successful privileged *read*.

    A read has no mutation to bind to, so the record is committed in its own
    transaction before the response is serialized: if the audit fails, the request
    fails and no privileged data is served.
    """
    hook = platform_exception_hook(
        principal,
        permission=permission,
        action=action,
        resource_type=resource_type,
        resource_reference=resource_reference,
        owner_customer_id=owner_customer_id,
        correlation_id=correlation_id,
    )
    if hook is None:
        return
    session.rollback()  # release any autobegun read transaction
    with session.begin():
        hook(session)
