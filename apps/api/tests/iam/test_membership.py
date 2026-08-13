"""Organization membership lifecycle (DB-backed): invite → accept → list → change
role → revoke, with privilege-escalation and last-admin safeguards."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.modules.iam.domain import OrganizationRole

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _customer_org_with_owner(admin: TestClient) -> tuple[TestClient, UUID, UUID]:
    """Create a customer org owned by a fresh user. Returns (owner_client, org_id, owner_id)."""
    customer_id = iam_support.create_customer(admin)
    owner_client = iam_support.new_client()
    owner_id = iam_support.register_verify_login(owner_client)
    resp = admin.post(
        "/api/v1/organizations",
        json={
            "organization_type": "CUSTOMER",
            "display_name": "Family Office",
            "customer_id": str(customer_id),
            "owner_user_id": str(owner_id),
        },
    )
    assert resp.status_code == 201, resp.text
    return owner_client, UUID(resp.json()["id"]), owner_id


@requires_db
def test_owner_can_invite_and_member_can_accept() -> None:
    admin = iam_support.platform_admin_client()
    owner_client, org_id, _ = _customer_org_with_owner(admin)

    assistant_client = iam_support.new_client()
    assistant_email = f"assistant+{uuid4().hex[:8]}@example.com"
    iam_support.register_verify_login(assistant_client, email=assistant_email)

    invite = owner_client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json={"email": assistant_email, "role": "CUSTOMER_ASSISTANT"},
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["invitation_token"]

    accepted = assistant_client.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "CUSTOMER_ASSISTANT"

    members = owner_client.get(f"/api/v1/organizations/{org_id}/members")
    assert members.status_code == 200
    assert len(members.json()) == 2


@requires_db
def test_invitation_is_bound_to_invited_email() -> None:
    admin = iam_support.platform_admin_client()
    owner_client, org_id, _ = _customer_org_with_owner(admin)
    invite = owner_client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json={"email": f"intended+{uuid4().hex[:8]}@example.com", "role": "CUSTOMER_ASSISTANT"},
    )
    token = invite.json()["invitation_token"]
    # A different user cannot accept someone else's invitation.
    intruder = iam_support.new_client()
    iam_support.register_verify_login(intruder)
    assert (
        intruder.post("/api/v1/auth/invitations/accept", json={"token": token}).status_code == 400
    )


@requires_db
def test_owner_cannot_invite_role_invalid_for_org_type() -> None:
    admin = iam_support.platform_admin_client()
    owner_client, org_id, _ = _customer_org_with_owner(admin)
    denied = owner_client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json={"email": f"x+{uuid4().hex[:8]}@example.com", "role": "OPERATOR_ADMIN"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "privilege_escalation_denied"


@requires_db
def test_owner_cannot_escalate_to_platform_role() -> None:
    admin = iam_support.platform_admin_client()
    owner_client, org_id, _ = _customer_org_with_owner(admin)
    denied = owner_client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json={"email": f"x+{uuid4().hex[:8]}@example.com", "role": "PLATFORM_ADMIN"},
    )
    assert denied.status_code == 403


@requires_db
def test_last_admin_cannot_revoke_self() -> None:
    admin = iam_support.platform_admin_client()
    owner_client, org_id, _ = _customer_org_with_owner(admin)
    members = owner_client.get(f"/api/v1/organizations/{org_id}/members").json()
    owner_membership_id = members[0]["id"]
    denied = owner_client.delete(f"/api/v1/organizations/{org_id}/members/{owner_membership_id}")
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "last_admin_protection"


@requires_db
def test_role_change_and_revoke_affect_access() -> None:
    admin = iam_support.platform_admin_client()
    owner_client, org_id, _ = _customer_org_with_owner(admin)

    assistant_client = iam_support.new_client()
    assistant_email = f"assistant+{uuid4().hex[:8]}@example.com"
    iam_support.register_verify_login(assistant_client, email=assistant_email)
    token = owner_client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json={"email": assistant_email, "role": "CUSTOMER_ASSISTANT"},
    ).json()["invitation_token"]
    membership = assistant_client.post(
        "/api/v1/auth/invitations/accept", json={"token": token}
    ).json()

    # Assistant cannot manage members.
    assert assistant_client.get(f"/api/v1/organizations/{org_id}/members").status_code == 403

    # Promote to owner, then the assistant can manage members.
    promoted = owner_client.post(
        f"/api/v1/organizations/{org_id}/members/{membership['id']}/role",
        json={"role": "CUSTOMER_OWNER"},
    )
    assert promoted.status_code == 200
    assert assistant_client.get(f"/api/v1/organizations/{org_id}/members").status_code == 200

    # Revoke the (now) second owner; access is removed.
    revoked = owner_client.delete(f"/api/v1/organizations/{org_id}/members/{membership['id']}")
    assert revoked.status_code == 200
    assert assistant_client.get(f"/api/v1/organizations/{org_id}/members").status_code == 403


@requires_db
def test_platform_roles_not_valid_in_customer_org() -> None:
    # Guard the domain rule directly for clarity.
    from sky_bridge_jet.modules.iam.domain import OrganizationType, role_is_valid_for_org_type

    assert (
        role_is_valid_for_org_type(OrganizationRole.CUSTOMER_OWNER, OrganizationType.CUSTOMER)
        is True
    )
    assert (
        role_is_valid_for_org_type(OrganizationRole.PLATFORM_ADMIN, OrganizationType.CUSTOMER)
        is False
    )
