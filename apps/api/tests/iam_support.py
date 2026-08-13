"""Shared authentication helpers for the test suites (Phase 8).

The global auth gate means every non-public request needs a session. Rather than
weakening the gate, suites authenticate through these helpers — analogous to how
Phase 6 updated fixtures instead of loosening the compliance gate.

``tests/`` is on ``sys.path`` (a top-level ``conftest.py`` lives there), so this
module is importable as ``import iam_support`` from any test package.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient

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
    Organization,
    OrganizationMembership,
    User,
)

_PASSWORD = "CorrectHorse12"


def new_client() -> TestClient:
    return TestClient(app)


def integration_client() -> TestClient:
    """The default suite client.

    Under RUN_DATABASE_INTEGRATION it is an authenticated platform-admin client so
    the Phase 2–7 suites exercise real routes through the enforced gate. Without the
    DB it is a plain client (only public/OpenAPI tests run, DB tests skip).
    """
    if os.getenv("RUN_DATABASE_INTEGRATION") == "1":
        return platform_admin_client()
    return new_client()


def register_verify_login(client: TestClient, *, email: str | None = None) -> UUID:
    """Register, verify, and log a fresh user in; set its CSRF header. Returns id."""
    email = email or f"user+{uuid4().hex[:10]}@example.com"
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert reg.status_code == 201, reg.text
    body = reg.json()
    client.post("/api/v1/auth/verify-email", json={"token": body["verification_token"]})
    login(client, email)
    return UUID(body["user"]["id"])


def login(client: TestClient, email: str, password: str = _PASSWORD) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]


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


def platform_admin_client() -> TestClient:
    """An authenticated client whose user is a platform admin (broad access).

    Used by the Phase 2–7 suites: a platform principal is cross-tenant, so existing
    resource flows keep working while the gate stays fully enforced. Multiple
    platform admins may coexist (unlike the single bootstrap product owner).
    """
    client = new_client()
    user_id = register_verify_login(client)
    _grant_membership(
        user_id,
        organization_type=OrganizationType.PLATFORM,
        role=OrganizationRole.PLATFORM_ADMIN,
        display_name="Sky Bridge Jet",
    )
    return client


def product_owner_client() -> TestClient:
    """An authenticated product-owner client (all permissions)."""
    client = new_client()
    user_id = register_verify_login(client)
    _grant_membership(
        user_id,
        organization_type=OrganizationType.PLATFORM,
        role=OrganizationRole.PRODUCT_OWNER,
        display_name="Sky Bridge Jet",
    )
    return client


def platform_role_client(role: OrganizationRole) -> TestClient:
    """An authenticated client holding a single platform role (least privilege)."""
    client = new_client()
    user_id = register_verify_login(client)
    _grant_membership(
        user_id,
        organization_type=OrganizationType.PLATFORM,
        role=role,
        display_name="Sky Bridge Jet",
    )
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
    """A CUSTOMER_OWNER user bound to the given customer. Returns (client, org_id)."""
    client = new_client()
    user_id = register_verify_login(client)
    org_id = _grant_membership(
        user_id,
        organization_type=OrganizationType.CUSTOMER,
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=customer_id,
        display_name="Customer Org",
    )
    return client, org_id


def operator_role_client(operator_id: UUID, role: OrganizationRole) -> tuple[TestClient, UUID]:
    """An operator-staff user bound to the given operator. Returns (client, org_id)."""
    client = new_client()
    user_id = register_verify_login(client)
    org_id = _grant_membership(
        user_id,
        organization_type=OrganizationType.OPERATOR,
        role=role,
        operator_id=operator_id,
        display_name="Operator Org",
    )
    return client, org_id


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
