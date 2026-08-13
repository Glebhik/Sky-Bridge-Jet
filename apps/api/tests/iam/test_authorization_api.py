"""Resource/role authorization at the API boundary (DB-backed).

Proves the high-consequence bindings: compliance review requires a platform
reviewer (an operator can never approve its own admission), financial onboarding is
operator-scoped, refunds require a finance/admin principal, and organization
creation requires platform admin.
"""

from __future__ import annotations

import os
from uuid import uuid4

import iam_support
import pytest

from sky_bridge_jet.modules.iam.domain import OrganizationRole

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_REVIEW_BODY = {"action": "APPROVE", "actor_type": "PLATFORM_REVIEWER"}


@requires_db
def test_operator_cannot_review_own_admission() -> None:
    admin = iam_support.platform_admin_client()
    operator_id = iam_support.create_operator(admin)
    # Set up a submitted admission as the platform admin.
    assert admin.post(f"/api/v1/operators/{operator_id}/admission").status_code == 201
    assert admin.post(f"/api/v1/operators/{operator_id}/admission/submit").status_code == 200

    # The operator's own admin has no compliance-review permission.
    operator_client, _ = iam_support.operator_role_client(
        operator_id, OrganizationRole.OPERATOR_ADMIN
    )
    denied = operator_client.post(
        f"/api/v1/operators/{operator_id}/admission/review", json=_REVIEW_BODY
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "authorization_denied"

    # A platform compliance reviewer may decide.
    reviewer = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    approved = reviewer.post(f"/api/v1/operators/{operator_id}/admission/review", json=_REVIEW_BODY)
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


@requires_db
def test_financial_onboarding_is_operator_scoped() -> None:
    admin = iam_support.platform_admin_client()
    operator_a = iam_support.create_operator(admin)
    operator_b = iam_support.create_operator(admin)

    a_admin, _ = iam_support.operator_role_client(operator_a, OrganizationRole.OPERATOR_ADMIN)
    # Operator A's admin manages A's account.
    created = a_admin.post(f"/api/v1/operators/{operator_a}/financial-account")
    assert created.status_code == 201
    # ...but cannot touch operator B's financial onboarding.
    assert a_admin.post(f"/api/v1/operators/{operator_b}/financial-account").status_code == 403
    assert a_admin.get(f"/api/v1/operators/{operator_b}/financial-account").status_code == 403
    assert (
        a_admin.post(f"/api/v1/operators/{operator_b}/financial-account/synchronize").status_code
        == 403
    )


@requires_db
def test_operator_sales_cannot_manage_finance() -> None:
    admin = iam_support.platform_admin_client()
    operator_id = iam_support.create_operator(admin)
    sales, _ = iam_support.operator_role_client(operator_id, OrganizationRole.OPERATOR_SALES)
    # Sales has no financial-onboarding permission, even for its own operator.
    assert sales.post(f"/api/v1/operators/{operator_id}/financial-account").status_code == 403


@requires_db
def test_refund_requires_finance_permission() -> None:
    # A random payment id is fine: the permission dependency runs before the route,
    # so an unprivileged principal is refused regardless of the payment.
    operator_id = iam_support.create_operator(iam_support.platform_admin_client())
    operator_client, _ = iam_support.operator_role_client(
        operator_id, OrganizationRole.OPERATOR_SALES
    )
    denied = operator_client.post(
        f"/api/v1/payments/{uuid4()}/refunds",
        json={"idempotency_key": f"idem-{uuid4()}", "amount_minor": 100},
    )
    assert denied.status_code == 403


@requires_db
def test_organization_creation_requires_platform_admin() -> None:
    operator_id = iam_support.create_operator(iam_support.platform_admin_client())
    operator_client, _ = iam_support.operator_role_client(
        operator_id, OrganizationRole.OPERATOR_ADMIN
    )
    denied = operator_client.post(
        "/api/v1/organizations",
        json={"organization_type": "PLATFORM", "display_name": "Rogue Platform"},
    )
    assert denied.status_code == 403


@requires_db
def test_unauthenticated_requests_are_rejected() -> None:
    anon = iam_support.new_client()
    assert anon.get("/api/v1/auth/me").status_code == 401
    assert anon.post("/api/v1/customers", json={}).status_code == 401
    assert (
        anon.post(f"/api/v1/operators/{uuid4()}/admission/review", json=_REVIEW_BODY).status_code
        == 401
    )
    # Public routes remain reachable.
    assert anon.get("/health").status_code == 200
    assert anon.get("/api/v1/airports").status_code == 200
