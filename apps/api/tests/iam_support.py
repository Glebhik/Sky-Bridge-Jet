"""Shared authentication helpers for the test suites (Phase 8).

The global auth gate means every non-public request needs a session. Rather than
weakening the gate, suites authenticate through these helpers — analogous to how
Phase 6 updated fixtures instead of loosening the compliance gate.

``tests/`` is on ``sys.path`` (a top-level ``conftest.py`` lives there), so this
module is importable as ``import iam_support`` from any test package.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.main import app
from sky_bridge_jet.modules.iam.authz import MembershipContext, Principal
from sky_bridge_jet.modules.iam.dependencies import enforce_authentication
from sky_bridge_jet.modules.iam.domain import (
    OrganizationRole,
    OrganizationType,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import (
    ExternalIdentityLink,
    Organization,
    OrganizationMembership,
    User,
    UserSession,
)

_PASSWORD = "CorrectHorse12"


def new_client() -> TestClient:
    return TestClient(app)


def integration_client() -> TestClient:
    """The default suite client for the legacy Phase 2–7 business suites.

    Under RUN_DATABASE_INTEGRATION it is an authenticated PRODUCT_OWNER — the single
    documented, audited platform actor that holds every permission and, being a
    PLATFORM organization, exercises the platform exception for customer-chain writes
    (Phase 9.0.A-1). This lets pre-tenancy business tests keep building their
    scenarios through the fully-enforced authorization gate without weakening it; the
    dedicated cross-tenant isolation tests use properly scoped customer principals.
    Without the DB it is a plain client (only public/OpenAPI tests run, DB tests skip).
    """
    if os.getenv("RUN_DATABASE_INTEGRATION") == "1":
        return product_owner_client()
    return new_client()


def register_verify_login(
    client: TestClient,
    *,
    email: str | None = None,
    before_verify: Callable[[UUID], None] | None = None,
) -> UUID:
    """Register, verify, and log a fresh user in; set its CSRF header. Returns id.

    ``before_verify`` runs after registration but *before* email verification, so a
    caller granting a platform/operator/specific-customer membership does so ahead of
    verification — which makes Phase 9.0.B personal-customer self-provisioning skip that
    user (existing-membership precedence), matching production where such users are
    bootstrapped/invited rather than self-provisioned. Plain callers (no hook) get the
    normal self-registering individual who is auto-provisioned a personal customer.
    """
    email = email or f"user+{uuid4().hex[:10]}@example.com"
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert reg.status_code == 201, reg.text
    body = reg.json()
    user_id = UUID(body["user"]["id"])
    if before_verify is not None:
        before_verify(user_id)
    client.post("/api/v1/auth/verify-email", json={"token": body["verification_token"]})
    login(client, email)
    return user_id


def login(client: TestClient, email: str, password: str = _PASSWORD) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    # Existing platform fixtures represent already-MFA-assured staff. Phase 10.C keeps
    # that intent explicit in the stored session; dedicated no-MFA tests use the raw
    # password endpoint directly and prove denial.
    with SessionLocal() as session, session.begin():
        user = session.scalars(select(User).where(User.normalized_email == email.lower())).one()
        platform_membership = session.scalars(
            select(OrganizationMembership)
            .join(Organization, Organization.id == OrganizationMembership.organization_id)
            .where(
                OrganizationMembership.user_id == user.id,
                Organization.organization_type == OrganizationType.PLATFORM,
            )
        ).first()
        if platform_membership is not None:
            link = session.scalars(
                select(ExternalIdentityLink).where(
                    ExternalIdentityLink.provider == "fake",
                    ExternalIdentityLink.user_id == user.id,
                )
            ).first()
            if link is None:
                link = ExternalIdentityLink(
                    user_id=user.id,
                    provider="fake",
                    issuer="urn:sky-bridge-jet:test-identity",
                    subject=f"test-user:{user.id}",
                )
                session.add(link)
                session.flush()
            record = session.scalars(
                select(UserSession)
                .where(UserSession.user_id == user.id)
                .order_by(UserSession.created_at.desc())
            ).first()
            assert record is not None
            now = datetime.now(UTC)
            record.identity_provider = "fake"
            record.external_identity_link_id = link.id
            record.provider_auth_time = now
            record.mfa_verified_at = now
            record.assurance_expires_at = now + timedelta(hours=8)


def _grant_membership(
    user_id: UUID,
    *,
    organization_type: OrganizationType,
    role: OrganizationRole,
    customer_id: UUID | None = None,
    operator_id: UUID | None = None,
    display_name: str = "Test Org",
) -> UUID:
    with SessionLocal() as session, session.begin():
        org = Organization(
            organization_type=organization_type,
            display_name=display_name,
            customer_id=customer_id,
            operator_id=operator_id,
        )
        session.add(org)
        session.flush()
        session.add(OrganizationMembership(user_id=user_id, organization_id=org.id, role=role))
        return org.id


def _platform_grant(role: OrganizationRole) -> Callable[[UUID], None]:
    def _grant(user_id: UUID) -> None:
        _grant_membership(
            user_id,
            organization_type=OrganizationType.PLATFORM,
            role=role,
            display_name="Sky Bridge Jet",
        )

    return _grant


def platform_admin_client() -> TestClient:
    """An authenticated client whose user is a platform admin (broad access).

    Used by the Phase 2–7 suites: a platform principal is cross-tenant, so existing
    resource flows keep working while the gate stays fully enforced. Multiple
    platform admins may coexist (unlike the single bootstrap product owner).
    """
    client = new_client()
    register_verify_login(client, before_verify=_platform_grant(OrganizationRole.PLATFORM_ADMIN))
    return client


def product_owner_client() -> TestClient:
    """An authenticated product-owner client (all permissions)."""
    client, _ = product_owner_client_with_user()
    return client


def product_owner_client_with_user() -> tuple[TestClient, UUID]:
    """A product-owner client and its user id (grant precedes verify → no personal tenant)."""
    client = new_client()
    user_id = register_verify_login(
        client, before_verify=_platform_grant(OrganizationRole.PRODUCT_OWNER)
    )
    return client, user_id


def platform_role_client(role: OrganizationRole) -> TestClient:
    """An authenticated client holding a single platform role (least privilege)."""
    client = new_client()
    register_verify_login(client, before_verify=_platform_grant(role))
    return client


def create_customer(admin_client: TestClient) -> UUID:
    """Create a Customer aggregate via the API (as an authorized admin)."""
    resp = admin_client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Scoped Customer",
            "primary_email": f"cust+{uuid4().hex[:8]}@example.test",
            "preferred_currency": "EUR",
            "timezone": "Europe/Dublin",
        },
    )
    assert resp.status_code == 201, resp.text
    return UUID(resp.json()["id"])


def create_operator(admin_client: TestClient) -> UUID:
    resp = admin_client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Scoped Aviation {uuid4().hex[:6]}",
            "country_code": "IE",
            "contact_email": f"ops+{uuid4().hex[:8]}@example.test",
        },
    )
    assert resp.status_code == 201, resp.text
    return UUID(resp.json()["id"])


def customer_owner_client(admin_client: TestClient, customer_id: UUID) -> tuple[TestClient, UUID]:
    """A CUSTOMER_OWNER user bound to the given customer. Returns (client, org_id).

    The membership is granted before verification so the user is bound only to this
    specific customer (no additional auto-provisioned personal customer tenant).
    """
    client = new_client()
    org_holder: dict[str, UUID] = {}

    def _grant(user_id: UUID) -> None:
        org_holder["org_id"] = _grant_membership(
            user_id,
            organization_type=OrganizationType.CUSTOMER,
            role=OrganizationRole.CUSTOMER_OWNER,
            customer_id=customer_id,
            display_name="Customer Org",
        )

    register_verify_login(client, before_verify=_grant)
    return client, org_holder["org_id"]


def member_client_for_org(organization_id: UUID, role: OrganizationRole) -> TestClient:
    """Register a fresh user and add them to an EXISTING organization in ``role``."""
    client = new_client()

    def _grant(user_id: UUID) -> None:
        with SessionLocal() as session, session.begin():
            session.add(
                OrganizationMembership(user_id=user_id, organization_id=organization_id, role=role)
            )

    register_verify_login(client, before_verify=_grant)
    return client


def operator_role_client(operator_id: UUID, role: OrganizationRole) -> tuple[TestClient, UUID]:
    """An operator-staff user bound to the given operator. Returns (client, org_id)."""
    client = new_client()
    org_holder: dict[str, UUID] = {}

    def _grant(user_id: UUID) -> None:
        org_holder["org_id"] = _grant_membership(
            user_id,
            organization_type=OrganizationType.OPERATOR,
            role=role,
            operator_id=operator_id,
            display_name="Operator Org",
        )

    register_verify_login(client, before_verify=_grant)
    return client, org_holder["org_id"]


def suspend_user(user_id: UUID) -> None:
    with SessionLocal() as session, session.begin():
        user = session.get(User, user_id)
        assert user is not None
        user.status = UserStatus.SUSPENDED


# A detached, DB-free admin principal for pure-unit API tests that override get_db
# with an in-memory database. It bypasses the session lookup while keeping the gate
# in force everywhere else.
_UNIT_ADMIN_PRINCIPAL = Principal(
    user_id=uuid4(),
    session_id=uuid4(),
    status=UserStatus.ACTIVE,
    memberships=(
        MembershipContext(
            organization_id=uuid4(),
            organization_type=OrganizationType.PLATFORM,
            role=OrganizationRole.PRODUCT_OWNER,
        ),
    ),
)


def override_admin_principal() -> None:
    """Install a dependency override that authenticates unit requests as an admin.

    For SQLite-backed unit tests that already override ``get_db``; cleared by the
    test's usual ``app.dependency_overrides.clear()``.
    """

    def _dep(request: Request) -> None:
        request.state.principal = _UNIT_ADMIN_PRINCIPAL

    app.dependency_overrides[enforce_authentication] = _dep


# --------------------------------------------------------------------------- #
# Aviation scenario builders (driven by an authorized admin client)
# --------------------------------------------------------------------------- #
_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def _future_iso(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def make_operator_eligible(admin: TestClient, operator_id: str, aircraft_id: str) -> None:
    """Admit an operator and authorize an aircraft using an admin (platform) client."""
    if admin.get(f"/api/v1/operators/{operator_id}/admission").status_code != 200:
        admin.post(f"/api/v1/operators/{operator_id}/admission")
        admin.post(f"/api/v1/operators/{operator_id}/admission/submit")
        admin.post(
            f"/api/v1/operators/{operator_id}/admission/review",
            json={"action": "APPROVE", **_REVIEWER},
        )
        expiry = (datetime.now(UTC) + timedelta(days=365)).isoformat()
        for body in (
            {
                "evidence_type": "OPERATING_AUTHORITY",
                "reference_number": "AOC-1",
                "issuing_authority": "IAA",
                "jurisdiction": "IE",
                "expiry_date": expiry,
            },
            {
                "evidence_type": "INSURANCE",
                "insurer_name": "Acme",
                "reference_number": "POL-1",
                "expiry_date": expiry,
            },
        ):
            evidence = admin.post(f"/api/v1/operators/{operator_id}/evidence", json=body).json()
            admin.post(
                f"/api/v1/evidence/{evidence['id']}/review",
                json={"action": "VERIFY", **_REVIEWER},
            )
    if (
        admin.get(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization"
        ).status_code
        != 200
    ):
        admin.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
            json={"authority_basis": "OWNED"},
        )
        admin.post(f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/submit")
        admin.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review",
            json={"action": "APPROVE", **_REVIEWER},
        )


def full_booking_scenario(
    admin: TestClient, airports: list[dict[str, Any]], *, confirm: bool = True
) -> dict[str, Any]:
    """Build customer→operator→aircraft→trip→offer→select→booking→payment as admin.

    Returns the created identifiers, including the ``customer_id`` so a caller can
    bind a scoped CUSTOMER_OWNER principal to it for isolation tests.
    """
    customer_id = str(create_customer(admin))
    operator = admin.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Scenario Air {uuid4().hex[:6]}",
            "country_code": "IE",
            "contact_email": f"ops-{uuid4().hex[:8]}@example.test",
        },
    ).json()
    aircraft = admin.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator["id"],
            "manufacturer": "Cessna",
            "model": "Citation CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 7,
        },
    ).json()
    make_operator_eligible(admin, operator["id"], aircraft["id"])
    trip = admin.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer_id,
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 2,
                }
            ],
        },
    ).json()
    admin.post(
        f"/api/v1/trip-requests/{trip['id']}/submit", json={"expected_version": trip["version"]}
    )
    offer = admin.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip["id"],
            "operator_id": operator["id"],
            "aircraft_id": aircraft["id"],
            "currency": "EUR",
            "operator_amount_minor": 1_000_000,
            "tax_amount_minor": 50_000,
            "valid_until": _future_iso(),
        },
    ).json()
    admin.post(f"/api/v1/offers/{offer['id']}/submit")
    admin.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    booking = admin.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    ).json()
    if confirm:
        confirmed = admin.post(
            f"/api/v1/bookings/{booking['id']}/confirm", json={"operator_id": operator["id"]}
        )
        assert confirmed.status_code == 200, confirmed.text
        booking = confirmed.json()
    payment = admin.post(f"/api/v1/bookings/{booking['id']}/payment").json()
    return {
        "customer_id": customer_id,
        "operator_id": operator["id"],
        "aircraft_id": aircraft["id"],
        "trip_id": trip["id"],
        "offer_id": offer["id"],
        "booking_id": booking["id"],
        "payment_id": payment["id"],
    }
