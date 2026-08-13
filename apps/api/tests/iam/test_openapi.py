"""OpenAPI contract for the identity module (no DB required)."""

from __future__ import annotations

import iam_support


def _schema() -> dict:
    client = iam_support.new_client()
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_iam_operations_published() -> None:
    schema = _schema()
    operation_ids = {
        op["operationId"]
        for path in schema["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    }
    assert {
        "registerUser",
        "verifyEmail",
        "login",
        "logout",
        "logoutAll",
        "getMe",
        "requestPasswordReset",
        "confirmPasswordReset",
        "acceptInvitation",
        "createOrganization",
        "createInvitation",
        "listOrganizationMembers",
        "changeMemberRole",
        "revokeMembership",
        "setUserStatus",
    } <= operation_ids


def test_no_secret_fields_in_schema() -> None:
    raw = iam_support.new_client().get("/openapi.json").text.lower()
    # Server-side secrets must never surface as API fields.
    assert "password_hash" not in raw
    assert "token_hash" not in raw
    assert "normalized_email" not in raw


def test_user_response_has_no_password() -> None:
    schema = _schema()
    props = schema["components"]["schemas"]["UserResponse"]["properties"]
    assert "password" not in props
    assert "password_hash" not in props
