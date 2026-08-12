"""API-level operator financial-onboarding lifecycle (default fake connect provider).

Stripe stays disabled, so the API uses the deterministic fake connect provider:
no network, no credentials. This proves the onboarding endpoints, the conflict
envelope, and the explainable eligibility endpoint end-to-end.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from ._support import requires_db


def _operator(client: TestClient) -> str:
    response = client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Financial Ops {uuid4()}",
            "country_code": "IE",
            "contact_email": f"fin-{uuid4()}@example.test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@requires_db
def test_create_and_get_connected_account(client: TestClient, airports: list) -> None:
    operator_id = _operator(client)
    created = client.post(f"/api/v1/operators/{operator_id}/financial-account")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["operator_id"] == operator_id
    assert body["payment_provider"] == "FAKE"
    assert body["onboarding_status"] == "REQUIREMENTS_DUE"
    assert body["provider_account_reference"].startswith("acct_")

    fetched = client.get(f"/api/v1/operators/{operator_id}/financial-account")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]

    # No secret material is ever exposed by the connected-account resource.
    assert "secret" not in fetched.text.lower()


@requires_db
def test_duplicate_account_conflicts(client: TestClient, airports: list) -> None:
    operator_id = _operator(client)
    assert client.post(f"/api/v1/operators/{operator_id}/financial-account").status_code == 201
    duplicate = client.post(f"/api/v1/operators/{operator_id}/financial-account")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "connected_account_exists"


@requires_db
def test_onboarding_link_issued(client: TestClient, airports: list) -> None:
    operator_id = _operator(client)
    client.post(f"/api/v1/operators/{operator_id}/financial-account")
    link = client.post(f"/api/v1/operators/{operator_id}/financial-account/onboarding-link")
    assert link.status_code == 200
    assert link.json()["url"].startswith("https://")


@requires_db
def test_eligibility_is_explainable_and_not_eligible_when_pending(
    client: TestClient, airports: list
) -> None:
    operator_id = _operator(client)
    client.post(f"/api/v1/operators/{operator_id}/financial-account")
    response = client.get(f"/api/v1/operators/{operator_id}/financial-eligibility")
    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is False
    assert "REQUIREMENTS_DUE" in body["reasons"]


@requires_db
def test_eligibility_without_account_reports_no_connected_account(
    client: TestClient, airports: list
) -> None:
    operator_id = _operator(client)
    response = client.get(f"/api/v1/operators/{operator_id}/financial-eligibility")
    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is False
    assert body["reasons"] == ["NO_CONNECTED_ACCOUNT"]


@requires_db
def test_unknown_operator_returns_404(client: TestClient, airports: list) -> None:
    missing = uuid4()
    assert client.post(f"/api/v1/operators/{missing}/financial-account").status_code == 404
    assert client.get(f"/api/v1/operators/{missing}/financial-account").status_code == 404
