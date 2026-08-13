"""OpenAPI contract checks for Phase 7 (no database required).

Confirms the financial-onboarding and webhook operations are published, the
payment schema exposes the new provider/SCA fields, and no secret configuration
(secret key, webhook secret) leaks into the API schema.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _schema(client: TestClient) -> dict:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_financial_operations_are_published(client: TestClient) -> None:
    schema = _schema(client)
    operation_ids = {
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert {
        "createOperatorConnectedAccount",
        "getOperatorConnectedAccount",
        "createOperatorOnboardingLink",
        "synchronizeOperatorConnectedAccount",
        "getOperatorFinancialEligibility",
        "stripeWebhook",
    } <= operation_ids


def test_payment_response_exposes_provider_and_sca_fields(client: TestClient) -> None:
    schema = _schema(client)
    properties = schema["components"]["schemas"]["PaymentResponse"]["properties"]
    assert "payment_provider" in properties
    assert "provider_status" in properties
    assert "requires_customer_action" in properties
    assert "client_action" in properties


def test_no_stripe_secrets_leak_into_schema(client: TestClient) -> None:
    raw = client.get("/openapi.json").text.lower()
    # Configuration secrets must never appear as API fields.
    assert "stripe_secret_key" not in raw
    assert "webhook_secret" not in raw
    assert "sk_test" not in raw
    assert "sk_live" not in raw


def test_connected_account_schema_has_no_bank_or_identity_fields(client: TestClient) -> None:
    schema = _schema(client)
    properties = schema["components"]["schemas"]["ConnectedAccountResponse"]["properties"]
    forbidden = {"iban", "bank_account", "routing_number", "ssn", "tax_id", "beneficial_owner"}
    assert forbidden.isdisjoint(properties.keys())
