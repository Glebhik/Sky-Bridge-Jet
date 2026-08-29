"""Customer- and operator-chain resource authorization (Phase 9.0.A-1 / 9.0.A-2).

This is the enforcement *seam* that closes the Phase 8 authorization debt for the
customer chain (9.0.A-1) and the operator chain (9.0.A-2). It reuses the Phase 8
primitives — ``Principal``, ``ResourceScope``, ``is_authorized`` — and adds only two
things:

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
from sky_bridge_jet.modules.compliance.models import ComplianceEvidence
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError
from sky_bridge_jet.modules.core_aviation.models import (
    Aircraft,
    Customer,
    Operator,
    Passenger,
    TripRequest,
)
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


def is_customer_view(principal: Principal, owner_customer_id: UUID | None) -> bool:
    """Whether a response should be the customer-safe projection (Phase 9.0.B).

    True when the principal owns the customer tenant via a CUSTOMER membership — an
    ordinary customer sees only the safe view. A platform or operator viewer (who does
    not own the customer tenant) receives the full internal response unchanged.
    """
    return owner_customer_id is not None and any(
        m.customer_id == owner_customer_id for m in _customer_memberships(principal)
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


def active_platform_organization_id(
    principal: Principal,
    requested_organization_id: UUID | None,
    permission: Permission,
) -> UUID:
    """Resolve one exact PLATFORM context and require its own permission.

    Global permissions must not be borrowed from a different membership when the
    request explicitly selected a CUSTOMER or OPERATOR organization. As with the
    customer/operator resolvers, a sole eligible PLATFORM membership is safely
    derived when no header is needed; multiple eligible platform memberships require
    an explicit, already membership-validated organization header.
    """
    eligible = [
        membership
        for membership in principal.memberships
        if membership.organization_type is OrganizationType.PLATFORM
    ]
    if requested_organization_id is not None:
        match = next(
            (
                membership
                for membership in eligible
                if membership.organization_id == requested_organization_id
            ),
            None,
        )
        if match is None:
            raise AuthorizationError("Invalid active platform organization for this action")
    elif len(eligible) == 1:
        match = eligible[0]
    elif not eligible:
        raise AuthorizationError("No platform organization context for this action")
    else:
        raise AuthorizationError("Multiple platform organizations; specify the active organization")
    if permission not in match.permissions:
        raise AuthorizationError("You are not permitted to perform this action")
    return match.organization_id


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


# --------------------------------------------------------------------------- #
# Operator-chain resource authorization (Phase 9.0.A-2, ADR-042)
# --------------------------------------------------------------------------- #
# Mirrors the customer-chain seam for the OPERATOR tenant. Operator ownership
# (``aircraft.operator_id``, ``offer.operator_id``, ``booking.operator_id``,
# ``evidence.operator_id``, and the ``operator_id`` path segment of the compliance
# routes) is immutable, so the same resolve-then-act discipline is race-free. A
# platform principal acting cross-operator by virtue of a platform role — never
# operator membership — is the audited operator platform exception.


def _operator_memberships(principal: Principal) -> list[MembershipContext]:
    return [
        m
        for m in principal.memberships
        if m.organization_type is OrganizationType.OPERATOR and m.operator_id is not None
    ]


def _owns_operator(principal: Principal, operator_id: UUID | None) -> bool:
    return operator_id is not None and any(
        m.operator_id == operator_id for m in _operator_memberships(principal)
    )


def _sees_operator_tenant(principal: Principal, operator_id: UUID) -> bool:
    """Whether the principal may even know the operator tenant exists (403 vs 404)."""
    if _owns_operator(principal, operator_id):
        return True
    return any(m.organization_type is OrganizationType.PLATFORM for m in principal.memberships)


def active_operator_id(principal: Principal, requested_organization_id: UUID | None) -> UUID:
    """Resolve and validate the acting operator for an operator write.

    Mirrors :func:`active_customer_id`: one eligible OPERATOR org auto-selects; several
    require a membership-validated ``X-Organization-Id``; CUSTOMER/PLATFORM orgs are
    never an ordinary operator context (they use the platform exception path).
    """
    eligible = _operator_memberships(principal)
    if requested_organization_id is not None:
        match = next((m for m in eligible if m.organization_id == requested_organization_id), None)
        if match is None or match.operator_id is None:
            # Do not disclose whether the org exists or is merely non-operator.
            raise AuthorizationError("Invalid active organization for this action")
        return match.operator_id
    if len(eligible) == 1:
        assert eligible[0].operator_id is not None
        return eligible[0].operator_id
    if not eligible:
        raise AuthorizationError("No operator organization context for this action")
    raise AuthorizationError("Multiple operator organizations; specify the active organization")


def require_operator_access(
    principal: Principal, permission: Permission, owner_operator_id: UUID | None
) -> None:
    """Enforce access to an operator-owned resource (deny by default, 403 vs 404).

    - ``owner_operator_id is None`` (resource absent) → 404;
    - authorized (owning operator, or platform with the permission) → allow;
    - visible tenant but lacking the permission → 403;
    - otherwise (cross-operator / no visibility) → 404 (existence concealed).
    """
    if owner_operator_id is None:
        raise ResourceNotFoundError("Resource was not found")
    if is_authorized(principal, permission, ResourceScope.operator(owner_operator_id)):
        return
    if _sees_operator_tenant(principal, owner_operator_id):
        raise AuthorizationError("You are not permitted to perform this action")
    raise ResourceNotFoundError("Resource was not found")


def resolve_write_operator(
    session: Session,
    principal: Principal,
    *,
    permission: Permission,
    body_operator_id: UUID | None,
    requested_organization_id: UUID | None,
) -> UUID:
    """Authoritative operator for an operator create/write, derived server-side.

    An operator principal acts within its validated active OPERATOR organization; a
    body ``operator_id`` may only *confirm* that same tenant (a mismatch is concealed
    as 404). A platform principal holding ``permission`` may act for an explicit,
    existing operator (the audited platform exception). Never invents an operator id.
    """
    if _operator_memberships(principal):
        derived = active_operator_id(principal, requested_organization_id)
        if not is_authorized(principal, permission, ResourceScope.operator(derived)):
            raise AuthorizationError("You are not permitted to perform this action")
        if body_operator_id is not None and body_operator_id != derived:
            # Never act on, or confirm the existence of, another operator tenant.
            raise ResourceNotFoundError("Operator was not found")
        return derived
    if body_operator_id is not None and is_authorized(
        principal, permission, ResourceScope.operator(body_operator_id)
    ):
        if not operator_exists(session, body_operator_id):
            raise ResourceNotFoundError("Operator was not found")
        return body_operator_id
    raise AuthorizationError("You are not permitted to perform this action")


def require_booking_cancel_access(
    principal: Principal,
    *,
    owner_customer_id: UUID | None,
    owner_operator_id: UUID | None,
) -> None:
    """Authorize a booking cancellation from either the customer or the operator side.

    The customer side (owner via booking→trip→customer, ``trip.write``) is preserved
    from Phase 9.0.A-1; the operator side (owner via ``booking.operator_id``,
    ``booking.decide``) is added here. Platform principals holding either permission
    are cross-tenant and audited by the caller. A wholly absent booking (both owners
    ``None``) → 404; a visible-but-unauthorized tenant → 403; otherwise concealed 404.
    """
    if owner_customer_id is None and owner_operator_id is None:
        raise ResourceNotFoundError("Resource was not found")
    if owner_customer_id is not None and is_authorized(
        principal, Permission.TRIP_WRITE, ResourceScope.customer(owner_customer_id)
    ):
        return
    if owner_operator_id is not None and is_authorized(
        principal, Permission.BOOKING_DECIDE, ResourceScope.operator(owner_operator_id)
    ):
        return
    if (owner_customer_id is not None and _sees_customer_tenant(principal, owner_customer_id)) or (
        owner_operator_id is not None and _sees_operator_tenant(principal, owner_operator_id)
    ):
        raise AuthorizationError("You are not permitted to perform this action")
    raise ResourceNotFoundError("Resource was not found")


def require_booking_read_access(
    principal: Principal,
    *,
    owner_customer_id: UUID | None,
    owner_operator_id: UUID | None,
) -> None:
    """Authorize a booking read from the operator side or the customer/platform side.

    A genuine owning operator (member of ``booking.operator_id``) is a party to the
    booking and receives the full response. Everyone else falls to the customer/platform
    policy (Phase 9.0.B): the owning customer is allowed and served a customer-safe view
    by the caller, a platform viewer is allowed the full response (and audited), and a
    cross-tenant probe gets 404.
    """
    if owner_customer_id is None and owner_operator_id is None:
        raise ResourceNotFoundError("Resource was not found")
    if (
        owner_operator_id is not None
        and _owns_operator(principal, owner_operator_id)
        and is_authorized(
            principal, Permission.BOOKING_READ, ResourceScope.operator(owner_operator_id)
        )
    ):
        return
    require_customer_access(principal, Permission.BOOKING_READ, owner_customer_id)


# --------------------------------------------------------------------------- #
# Operator ownership resolvers (read on the request session; immutable ownership)
# --------------------------------------------------------------------------- #
def operator_exists(session: Session, operator_id: UUID) -> bool:
    return session.get(Operator, operator_id) is not None


def operator_of_aircraft(session: Session, aircraft_id: UUID) -> UUID | None:
    return session.scalar(select(Aircraft.operator_id).where(Aircraft.id == aircraft_id))


def operator_of_offer(session: Session, offer_id: UUID) -> UUID | None:
    return session.scalar(select(OperatorOffer.operator_id).where(OperatorOffer.id == offer_id))


def operator_of_booking(session: Session, booking_id: UUID) -> UUID | None:
    return session.scalar(select(Booking.operator_id).where(Booking.id == booking_id))


def operator_of_payment(session: Session, payment_id: UUID) -> UUID | None:
    return session.scalar(
        select(Booking.operator_id)
        .join(Payment, Payment.booking_id == Booking.id)
        .where(Payment.id == payment_id)
    )


def operator_of_evidence(session: Session, evidence_id: UUID) -> UUID | None:
    return session.scalar(
        select(ComplianceEvidence.operator_id).where(ComplianceEvidence.id == evidence_id)
    )


# --------------------------------------------------------------------------- #
# Operator platform-exception auditing (reuses the Phase 9.0.A-1 append-only event)
# --------------------------------------------------------------------------- #
def is_operator_platform_exception(principal: Principal, owner_operator_id: UUID | None) -> bool:
    """True when access to ``owner_operator_id`` succeeds via a platform role rather
    than operator membership."""
    if owner_operator_id is None:
        return False
    return not _owns_operator(principal, owner_operator_id) and (
        _acting_platform_org(principal) is not None
    )


def platform_operator_exception_hook(
    principal: Principal,
    *,
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    owner_operator_id: UUID | None,
    correlation_id: str | None = None,
) -> AuditHook | None:
    """Return an append-only audit hook iff this operator access is a platform exception.

    Invoked inside the write service's transaction (via ``on_commit``) so the audit
    record commits atomically with — and rolls back with — the mutation.
    """
    if not is_operator_platform_exception(principal, owner_operator_id):
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


def audit_operator_platform_read(
    session: Session,
    principal: Principal,
    *,
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    owner_operator_id: UUID | None,
    correlation_id: str | None = None,
) -> None:
    """Persist an operator platform-exception audit for a successful privileged read.

    Committed in its own transaction before the response is serialized: if the audit
    fails, the request fails and no privileged data is served.
    """
    hook = platform_operator_exception_hook(
        principal,
        permission=permission,
        action=action,
        resource_type=resource_type,
        resource_reference=resource_reference,
        owner_operator_id=owner_operator_id,
        correlation_id=correlation_id,
    )
    if hook is None:
        return
    session.rollback()  # release any autobegun read transaction
    with session.begin():
        hook(session)


# --------------------------------------------------------------------------- #
# Payment operational authorization (Phase 9.0.A-3, ADR-043)
# --------------------------------------------------------------------------- #
# Internal payment operations (create/authorize/capture/void/refund) are a
# platform-only capability. Their success is recorded under a distinct, stable
# append-only security event so a payment mutation is never mislabelled as a read
# exception. Allocation and refund-list *reads* remain platform-read-only here; an
# owning customer/operator is denied (403, no safe financial projection yet) and a
# cross-tenant probe is concealed (404).

# Stable append-only security-audit event for a successful internal payment mutation.
PAYMENT_OPERATION_EVENT = "payment_operational_action"


def require_financial_platform_read(
    principal: Principal,
    permission: Permission,
    *,
    owner_customer_id: UUID | None,
    owner_operator_id: UUID | None,
) -> None:
    """Enforce a platform-only read of a confidential financial resource.

    Applies to the allocation and refund-list reads, whose responses expose the
    internal operator/platform split, settlement eligibility, and provider references.
    Only a platform viewer holding ``permission`` (e.g. ``payment.read``) receives the
    response; an owning customer or owning operator is temporarily denied with 403 (no
    customer/operator-safe financial projection exists yet — Phase 9.0.B); any other
    principal or a cross-tenant probe receives 404 so existence is concealed.
    """
    if owner_customer_id is None and owner_operator_id is None:
        raise ResourceNotFoundError("Resource was not found")
    if has_platform_permission(principal, permission):
        return
    owns_customer = owner_customer_id is not None and any(
        m.customer_id == owner_customer_id for m in _customer_memberships(principal)
    )
    if owns_customer or _owns_operator(principal, owner_operator_id):
        raise AuthorizationError("A safe view of this financial resource is not yet available")
    raise ResourceNotFoundError("Resource was not found")


def payment_operation_hook(
    principal: Principal,
    *,
    permission: Permission,
    action: str,
    resource_type: str,
    resource_reference: UUID | str,
    correlation_id: str | None = None,
) -> AuditHook:
    """An unconditional append-only audit hook for a successful internal payment mutation.

    The route already gates the actor to the required platform permission
    (``payment.operate`` / ``payment.refund``), so every invocation is a privileged
    platform action. The hook is run *inside* the payment service's transaction via
    ``on_commit`` and only on the success path, so the record commits atomically with
    the mutation and a failed/declined/replayed operation records nothing. Safe
    metadata only — never amounts, provider references, tokens, or PII.
    """
    user_id = principal.user_id
    org_id = _acting_platform_org(principal)
    detail = _exception_detail(
        permission, action, resource_type, resource_reference, correlation_id
    )

    def _hook(session: Session) -> None:
        AuditRepository(session).record(
            PAYMENT_OPERATION_EVENT, user_id=user_id, organization_id=org_id, detail=detail
        )

    return _hook
