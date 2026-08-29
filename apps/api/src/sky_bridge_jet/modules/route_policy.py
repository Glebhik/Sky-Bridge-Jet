"""Declarative authorization-policy registry for every registered route/method.

This is the single, explicit inventory of *how every route is authorized*. It exists
so a route can never become accessible merely because someone forgot to secure it: an
automated coverage test (``tests/test_route_policy_coverage.py``) compares this
registry against the live FastAPI route graph and fails on any unclassified, omitted,
duplicated, or unsafely-public route.

Dispositions carry intent, not enforcement — enforcement lives in the routers/seam.
Pending dispositions mark work owned by an explicitly named later PR; a pending route
is still protected by the global authentication gate (never anonymous).

Canonical route set (documented normalization): the 81 OpenAPI operations plus the 4
documentation/schema routes (`/docs`, `/docs/oauth2-redirect`, `/redoc`,
`/openapi.json`) that Starlette serves outside the OpenAPI schema = 85 entries.
HEAD/OPTIONS are ignored (auto-provided by Starlette). Phase 9.1.A added one operation:
the authenticated customer-account recovery endpoint (79 → 80 ops; 83 → 84 entries).
Phase 9.2.A adds one public operation: the enumeration-safe verification-resend endpoint
`POST /api/v1/auth/verification/resend` (80 → 81 ops; 84 → 85 entries).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Disposition(StrEnum):
    PUBLIC = "PUBLIC"
    # Authenticated and already bound to the correct actor/scope (Phase 8 or self).
    ALREADY_BOUND = "ALREADY_BOUND"
    # Bound to customer-chain resource authorization (Phase 9.0.A-1).
    PHASE_9_0A_1_BOUND = "PHASE_9_0A_1_BOUND"
    # Bound to operator-chain resource authorization (Phase 9.0.A-2).
    PHASE_9_0A_2_BOUND = "PHASE_9_0A_2_BOUND"
    # Bound to payment operational authorization (Phase 9.0.A-3).
    PHASE_9_0A_3_BOUND = "PHASE_9_0A_3_BOUND"
    # Customer provisioning & safe read models — the customer "my" list endpoints
    # bound in this PR (Phase 9.0.B). Existing routes that gained a customer-safe
    # projection keep their authorization-phase disposition; their notes record 9.0.B.
    PHASE_9_0B_BOUND = "PHASE_9_0B_BOUND"
    # Authenticated customer-account recovery — the self-service endpoint bound in this
    # PR (Phase 9.1.A). The typed audience-aware contract work on the eight shared routes
    # is schema-only and adds no route, so those keep their authorization-phase
    # disposition (their notes record the 9.1.A typed contract).
    PHASE_9_1A_BOUND = "PHASE_9_1A_BOUND"
    # Customer-owned payment initiation boundary (Phase 9.6.B0).
    PHASE_9_6B0_BOUND = "PHASE_9_6B0_BOUND"
    # Bounded internal platform compliance review center (Phase 9.8.A).
    PHASE_9_8A_BOUND = "PHASE_9_8A_BOUND"
    # Bounded internal payment exception and reconciliation operations (Phase 9.8.B).
    PHASE_9_8B_BOUND = "PHASE_9_8B_BOUND"
    PHASE_10B_BOUND = "PHASE_10B_BOUND"
    PHASE_10C_BOUND = "PHASE_10C_BOUND"


@dataclass(frozen=True)
class RoutePolicy:
    method: str
    path: str
    disposition: Disposition
    actor: str
    note: str = ""


def _p(method: str, path: str, disp: Disposition, actor: str, note: str = "") -> RoutePolicy:
    return RoutePolicy(method=method, path=path, disposition=disp, actor=actor, note=note)


_PUB = Disposition.PUBLIC
_AB = Disposition.ALREADY_BOUND
_P1 = Disposition.PHASE_9_0A_1_BOUND
_P2 = Disposition.PHASE_9_0A_2_BOUND
_P3 = Disposition.PHASE_9_0A_3_BOUND
_P0B = Disposition.PHASE_9_0B_BOUND
_P1A = Disposition.PHASE_9_1A_BOUND
_P96B0 = Disposition.PHASE_9_6B0_BOUND
_P98A = Disposition.PHASE_9_8A_BOUND
_P98B = Disposition.PHASE_9_8B_BOUND
_P10B = Disposition.PHASE_10B_BOUND
_P10C = Disposition.PHASE_10C_BOUND

ROUTE_POLICIES: tuple[RoutePolicy, ...] = (
    _p(
        "GET",
        "/api/v1/platform/operations/diagnostics",
        _P10C,
        "platform admin/product owner with MFA",
    ),
    _p("GET", "/api/v1/auth/platform/login", _PUB, "anonymous", "OIDC initiation"),
    _p("GET", "/api/v1/auth/platform/callback", _PUB, "provider", "OIDC callback"),
    _p("GET", "/api/v1/platform/pilot/state", _P10B, "platform (pilot.read)"),
    _p("POST", "/api/v1/platform/pilot/state", _P10B, "platform (pilot.manage)"),
    _p("GET", "/api/v1/platform/pilot/participants", _P10B, "platform (pilot.read)"),
    _p("POST", "/api/v1/platform/pilot/participants", _P10B, "platform (pilot.manage)"),
    _p(
        "GET",
        "/api/v1/platform/pilot/participants/{participant_id}",
        _P10B,
        "platform (pilot.read)",
    ),
    _p(
        "POST",
        "/api/v1/platform/pilot/participants/{participant_id}/status",
        _P10B,
        "platform (pilot.manage)",
    ),
    _p("GET", "/api/v1/platform/pilot/audits", _P10B, "platform (pilot.read)"),
    # ---- Platform / documentation / discovery (public) --------------------
    _p("GET", "/api/v1", _PUB, "anonymous", "versioned namespace root"),
    _p("GET", "/health", _PUB, "anonymous"),
    _p("GET", "/ready", _PUB, "anonymous"),
    _p("GET", "/docs", _PUB, "anonymous", "swagger UI (B4: disable/protect in prod)"),
    _p("GET", "/docs/oauth2-redirect", _PUB, "anonymous"),
    _p("GET", "/redoc", _PUB, "anonymous"),
    _p("GET", "/openapi.json", _PUB, "anonymous"),
    _p("GET", "/api/v1/airports", _PUB, "anonymous", "public airport discovery"),
    _p("GET", "/api/v1/airports/{airport_id}", _PUB, "anonymous"),
    # ---- Authentication (public initiation/recovery) ----------------------
    _p("POST", "/api/v1/auth/register", _PUB, "anonymous"),
    _p("POST", "/api/v1/auth/login", _PUB, "anonymous"),
    _p("POST", "/api/v1/auth/verify-email", _PUB, "anonymous"),
    _p(
        "POST",
        "/api/v1/auth/verification/resend",
        _PUB,
        "anonymous",
        "enumeration-safe verification resend (Phase 9.2.A)",
    ),
    _p("POST", "/api/v1/auth/password-reset", _PUB, "anonymous"),
    _p("POST", "/api/v1/auth/password-reset/confirm", _PUB, "anonymous"),
    _p("POST", "/api/v1/webhooks/stripe", _PUB, "provider", "signature-authenticated"),
    # ---- Authenticated self / Phase 8 bound -------------------------------
    _p("GET", "/api/v1/auth/me", _AB, "self"),
    _p(
        "GET",
        "/api/v1/me/operator-compliance-readiness",
        _AB,
        "operator",
        "Phase 9.7.C0 active-operator-safe compliance readiness",
    ),
    _p("GET", "/api/v1/me/operator-bookings", _AB, "operator", "Phase 9.5.B pending queue"),
    _p(
        "GET",
        "/api/v1/me/operator-operations",
        _AB,
        "operator",
        "Phase 9.8.D0 bounded active-operator operational handoffs",
    ),
    _p(
        "GET",
        "/api/v1/me/operator-operations/{operation_id}",
        _AB,
        "operator",
        "Phase 9.8.D0 active-operator operational handoff detail",
    ),
    _p(
        "GET",
        "/api/v1/me/operator-bookings/history",
        _AB,
        "operator",
        "Phase 9.7.B0 bounded active-operator Booking history",
    ),
    _p(
        "GET",
        "/api/v1/me/operator-bookings/{booking_id}",
        _AB,
        "operator",
        "Phase 9.7.B0 active-operator-safe Booking detail",
    ),
    _p(
        "GET",
        "/api/v1/me/operator-opportunities",
        _AB,
        "operator",
        "Phase 9.7.A0 admitted marketplace opportunity projection",
    ),
    _p(
        "GET",
        "/api/v1/me/operator-aircraft",
        _AB,
        "operator",
        "Phase 9.7.A1 bounded active-operator aircraft projection",
    ),
    _p(
        "POST",
        "/api/v1/me/operator-aircraft",
        _AB,
        "operator-admin",
        "Phase 9.7.D0 active-operator aircraft command",
    ),
    _p(
        "GET",
        "/api/v1/me/operator-aircraft/{aircraft_id}",
        _AB,
        "operator",
        "Phase 9.7.D0 active-operator-safe aircraft detail",
    ),
    _p(
        "POST",
        "/api/v1/me/operator-offers",
        _AB,
        "operator",
        "Phase 9.7.A1 active-operator Offer command",
    ),
    _p("POST", "/api/v1/auth/logout", _AB, "self"),
    _p("POST", "/api/v1/auth/logout-all", _AB, "self"),
    _p("POST", "/api/v1/auth/invitations/accept", _AB, "invited-self"),
    _p("POST", "/api/v1/organizations", _AB, "platform-admin"),
    _p("POST", "/api/v1/organizations/{organization_id}/invitations", _AB, "org-admin"),
    _p("GET", "/api/v1/organizations/{organization_id}/members", _AB, "org-admin"),
    _p(
        "POST",
        "/api/v1/organizations/{organization_id}/members/{membership_id}/role",
        _AB,
        "org-admin",
    ),
    _p(
        "DELETE",
        "/api/v1/organizations/{organization_id}/members/{membership_id}",
        _AB,
        "org-admin",
    ),
    _p("POST", "/api/v1/admin/users/{user_id}/status", _AB, "platform-admin"),
    _p("POST", "/api/v1/operators/{operator_id}/admission/review", _AB, "platform-reviewer"),
    _p("POST", "/api/v1/evidence/{evidence_id}/review", _AB, "platform-reviewer"),
    _p(
        "POST",
        "/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review",
        _AB,
        "platform-reviewer",
    ),
    _p(
        "GET", "/api/v1/operators/{operator_id}/financial-account", _AB, "operator/platform-finance"
    ),
    _p(
        "POST",
        "/api/v1/operators/{operator_id}/financial-account",
        _AB,
        "operator/platform-finance",
    ),
    _p(
        "POST",
        "/api/v1/operators/{operator_id}/financial-account/onboarding-link",
        _AB,
        "operator/platform-finance",
    ),
    _p(
        "POST",
        "/api/v1/operators/{operator_id}/financial-account/synchronize",
        _AB,
        "operator/platform-finance",
    ),
    _p(
        "GET",
        "/api/v1/operators/{operator_id}/financial-eligibility",
        _AB,
        "operator/platform-finance",
    ),
    # ---- Customer chain — bound in THIS PR (Phase 9.0.A-1) -----------------
    _p(
        "POST",
        "/api/v1/customers",
        _P1,
        "platform-admin",
        "controlled until 9.0.B self-provisioning",
    ),
    _p("GET", "/api/v1/customers/{customer_id}", _P1, "customer/platform"),
    _p("POST", "/api/v1/passengers", _P1, "customer/platform"),
    _p("GET", "/api/v1/passengers/{passenger_id}", _P1, "customer/platform"),
    _p("POST", "/api/v1/trip-requests", _P1, "customer/platform"),
    _p("GET", "/api/v1/trip-requests/{trip_request_id}", _P1, "customer/platform"),
    _p("POST", "/api/v1/trip-requests/{trip_request_id}/submit", _P1, "customer/platform"),
    _p("POST", "/api/v1/trip-requests/{trip_request_id}/cancel", _P1, "customer/platform"),
    _p("GET", "/api/v1/trip-requests/{trip_request_id}/offers", _P1, "platform (customer→9.0.B)"),
    _p(
        "POST",
        "/api/v1/trip-requests/{trip_request_id}/offers/{offer_id}/select",
        _P1,
        "customer/platform",
    ),
    _p("POST", "/api/v1/bookings", _P1, "customer/platform"),
    _p(
        "GET",
        "/api/v1/bookings/{booking_id}",
        _P1,
        "operator/platform (customer→9.0.B)",
        "operator read added in 9.0.A-2",
    ),
    _p("GET", "/api/v1/trip-requests/{trip_request_id}/booking", _P1, "platform (customer→9.0.B)"),
    _p(
        "POST",
        "/api/v1/bookings/{booking_id}/cancel",
        _P1,
        "customer/operator/platform",
        "operator cancel added in 9.0.A-2",
    ),
    _p("GET", "/api/v1/bookings/{booking_id}/payment", _P1, "platform (customer→9.0.B)"),
    _p("GET", "/api/v1/payments/{payment_id}", _P1, "platform (customer→9.0.B)"),
    # ---- Operator chain — bound in THIS PR (Phase 9.0.A-2) ----------------
    _p("POST", "/api/v1/operators", _P2, "platform-admin", "B2 controlled onboarding"),
    _p("GET", "/api/v1/operators/{operator_id}", _P2, "operator/platform"),
    _p("POST", "/api/v1/aircraft", _P2, "operator"),
    _p("GET", "/api/v1/aircraft/{aircraft_id}", _P2, "operator/platform"),
    _p("POST", "/api/v1/offers", _P2, "operator"),
    _p("GET", "/api/v1/offers/{offer_id}", _P2, "operator/platform"),
    _p("PATCH", "/api/v1/offers/{offer_id}", _P2, "operator"),
    _p("POST", "/api/v1/offers/{offer_id}/submit", _P2, "operator"),
    _p("POST", "/api/v1/offers/{offer_id}/withdraw", _P2, "operator"),
    _p("POST", "/api/v1/bookings/{booking_id}/confirm", _P2, "operator"),
    _p("POST", "/api/v1/bookings/{booking_id}/reject", _P2, "operator"),
    _p("GET", "/api/v1/operators/{operator_id}/admission", _P2, "operator/platform"),
    _p("POST", "/api/v1/operators/{operator_id}/admission", _P2, "operator"),
    _p("POST", "/api/v1/operators/{operator_id}/admission/submit", _P2, "operator"),
    _p("GET", "/api/v1/operators/{operator_id}/admission/audit-events", _P2, "operator/platform"),
    _p("GET", "/api/v1/operators/{operator_id}/evidence", _P2, "operator/platform"),
    _p("POST", "/api/v1/operators/{operator_id}/evidence", _P2, "operator"),
    _p("GET", "/api/v1/evidence/{evidence_id}", _P2, "operator/platform"),
    _p("GET", "/api/v1/evidence/{evidence_id}/audit-events", _P2, "operator/platform"),
    _p(
        "GET",
        "/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
        _P2,
        "operator/platform",
    ),
    _p(
        "POST",
        "/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
        _P2,
        "operator",
    ),
    _p(
        "POST",
        "/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/submit",
        _P2,
        "operator",
    ),
    _p(
        "GET",
        "/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/eligibility",
        _P2,
        "operator/platform",
    ),
    _p("GET", "/api/v1/operators/{operator_id}/eligibility", _P2, "operator/platform"),
    # ---- Payment operations — bound in THIS PR (Phase 9.0.A-3) ------------
    _p(
        "POST",
        "/api/v1/bookings/{booking_id}/payment",
        _P3,
        "platform (payment.operate)",
        "B3/D internal/trusted; not customer/operator",
    ),
    _p(
        "POST",
        "/api/v1/bookings/{booking_id}/payment/initiate",
        _P96B0,
        "customer (payment.initiate; own booking)",
        "server-derived amount/currency/provider; customer-safe response",
    ),
    _p(
        "GET",
        "/api/v1/payments/{payment_id}/allocation",
        _P3,
        "platform payment.read (customer/operator→9.0.B)",
        "confidential financial split",
    ),
    _p(
        "GET",
        "/api/v1/payments/{payment_id}/refunds",
        _P3,
        "platform payment.read (customer/operator→9.0.B)",
    ),
    _p("POST", "/api/v1/payments/{payment_id}/authorize", _P3, "platform (payment.operate)"),
    _p("POST", "/api/v1/payments/{payment_id}/capture", _P3, "platform (payment.operate)"),
    _p("POST", "/api/v1/payments/{payment_id}/void", _P3, "platform (payment.operate)"),
    _p(
        "POST",
        "/api/v1/payments/{payment_id}/refunds",
        _AB,
        "platform (payment.refund)",
        "payment.refund unchanged; ADR-043 removed finance-reviewer grant",
    ),
    _p(
        "GET",
        "/api/v1/platform/payments/exceptions",
        _P98B,
        "platform (payment.read)",
        "bounded exception discovery",
    ),
    _p(
        "GET",
        "/api/v1/platform/payments/{payment_id}",
        _P98B,
        "platform (payment.read)",
        "safe exact detail and bounded operation timeline",
    ),
    _p(
        "POST",
        "/api/v1/platform/payment-operations/{operation_id}/reconcile",
        _P98B,
        "platform (payment.operate)",
        "same durable UNKNOWN operation identity only",
    ),
    # ---- Customer provisioning & safe read models — bound in THIS PR (9.0.B) ----
    _p("GET", "/api/v1/me/trip-requests", _P0B, "customer (own; safe projection)"),
    _p("GET", "/api/v1/me/bookings", _P0B, "customer (own; safe projection)"),
    _p("GET", "/api/v1/me/payments", _P0B, "customer (own; safe status)"),
    # ---- Customer-account recovery — bound in THIS PR (Phase 9.1.A) ------------
    _p(
        "POST",
        "/api/v1/auth/customer-account/recover",
        _P1A,
        "customer-self",
        "authenticated + CSRF + rate-limited; server-derived identity; never public",
    ),
    # ---- Platform compliance review center (Phase 9.8.A) -----------------
    _p("GET", "/api/v1/platform/compliance/admissions", _P98A, "platform compliance reviewer"),
    _p(
        "GET",
        "/api/v1/platform/compliance/admissions/{admission_id}",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "POST",
        "/api/v1/platform/compliance/admissions/{admission_id}/review",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "GET",
        "/api/v1/platform/compliance/admissions/{admission_id}/audit-events",
        _P98A,
        "platform compliance reviewer",
    ),
    _p("GET", "/api/v1/platform/compliance/evidence", _P98A, "platform compliance reviewer"),
    _p(
        "GET",
        "/api/v1/platform/compliance/evidence/{evidence_id}",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "POST",
        "/api/v1/platform/compliance/evidence/{evidence_id}/review",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "GET",
        "/api/v1/platform/compliance/evidence/{evidence_id}/audit-events",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "GET",
        "/api/v1/platform/compliance/aircraft-authorizations",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "GET",
        "/api/v1/platform/compliance/aircraft-authorizations/{authorization_id}",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "POST",
        "/api/v1/platform/compliance/aircraft-authorizations/{authorization_id}/review",
        _P98A,
        "platform compliance reviewer",
    ),
    _p(
        "GET",
        "/api/v1/platform/compliance/aircraft-authorizations/{authorization_id}/audit-events",
        _P98A,
        "platform compliance reviewer",
    ),
)


def policy_index() -> dict[tuple[str, str], RoutePolicy]:
    """Return a (method, path) → policy map, raising on duplicate/contradictory keys."""
    index: dict[tuple[str, str], RoutePolicy] = {}
    for policy in ROUTE_POLICIES:
        key = (policy.method, policy.path)
        if key in index:
            raise ValueError(f"Duplicate route policy for {key}")
        index[key] = policy
    return index


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
# Documentation/schema routes are served by Starlette outside the OpenAPI schema.
DOCUMENTATION_ROUTES: tuple[str, ...] = (
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
)


def enumerate_app_routes(app: object) -> set[tuple[str, str]]:
    """Canonical (method, path) set of every registered route on the live app.

    Normalization: the OpenAPI operations (business + health/ready/root) union the
    four documentation routes; HEAD/OPTIONS are excluded (Starlette auto-provides
    them). This is the authoritative graph the registry must fully cover.
    """
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")
    routes: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            upper = method.upper()
            if upper in _HTTP_METHODS:
                routes.add((upper, path))
    for path in DOCUMENTATION_ROUTES:
        routes.add(("GET", path))
    return routes


def coverage_report(app: object) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return (registered-but-unclassified, classified-but-not-registered)."""
    registered = enumerate_app_routes(app)
    classified = set(policy_index().keys())
    return registered - classified, classified - registered
