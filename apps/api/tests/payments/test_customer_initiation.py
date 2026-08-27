"""Phase 9.6.B0 customer-safe payment initiation boundary."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.payments.domain import PaymentOperationType
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation

from ._support import booking_scenario, capture, new_key, refund, requires_db

pytestmark = requires_db

SAFE_KEYS = {
    "id",
    "booking_id",
    "status",
    "currency",
    "total_amount_minor",
    "authorized_amount_minor",
    "captured_amount_minor",
    "refunded_amount_minor",
    "requires_customer_action",
    "authorized_at",
    "captured_at",
    "cancelled_at",
    "created_at",
    "updated_at",
    "client_action",
}


def _customer_for(admin: TestClient, scenario: dict[str, Any]) -> TestClient:
    customer, org_id = iam_support.customer_owner_client(admin, UUID(scenario["customer"]["id"]))
    customer.headers["X-Organization-Id"] = str(org_id)
    return customer


def _initiate(client: TestClient, booking_id: str, key: str):
    return client.post(
        f"/api/v1/bookings/{booking_id}/payment/initiate",
        json={"idempotency_key": key},
    )


def test_customer_initiates_own_pending_booking_safely(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    customer = _customer_for(client, scenario)
    response = _initiate(customer, scenario["booking"]["id"], f"customer-{uuid4()}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == SAFE_KEYS
    assert body["status"] == "AUTHORIZED"
    assert body["currency"] == scenario["booking"]["currency"]
    assert body["total_amount_minor"] == scenario["booking"]["total_amount_minor"]
    assert body["authorized_amount_minor"] == body["total_amount_minor"]
    assert body["captured_amount_minor"] == 0
    assert body["refunded_amount_minor"] == 0
    assert body["client_action"] is None
    assert (
        client.get(f"/api/v1/trip-requests/{scenario['trip']['id']}").json()["status"]
        == "SUBMITTED"
    )
    assert client.get(f"/api/v1/offers/{scenario['offer']['id']}").json()["status"] == "SELECTED"
    assert (
        client.get(f"/api/v1/bookings/{scenario['booking']['id']}").json()["status"]
        == "PENDING_OPERATOR_CONFIRMATION"
    )

    with SessionLocal() as session:
        payments = (
            session.query(Payment).filter(Payment.booking_id == UUID(body["booking_id"])).all()
        )
        operations = (
            session.query(PaymentOperation)
            .filter(PaymentOperation.payment_id == payments[0].id)
            .all()
        )
        assert len(payments) == 1
        assert [operation.operation for operation in operations] == [PaymentOperationType.AUTHORIZE]


def test_same_key_replay_and_fresh_key_on_authorized_payment_do_not_duplicate(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    customer = _customer_for(client, scenario)
    key = f"customer-{uuid4()}"
    first = _initiate(customer, scenario["booking"]["id"], key)
    replay = _initiate(customer, scenario["booking"]["id"], key)
    fresh = _initiate(customer, scenario["booking"]["id"], f"customer-{uuid4()}")
    assert first.status_code == replay.status_code == fresh.status_code == 200
    assert first.json()["id"] == replay.json()["id"] == fresh.json()["id"]
    with SessionLocal() as session:
        assert (
            session.query(Payment).filter_by(booking_id=UUID(scenario["booking"]["id"])).count()
            == 1
        )
        assert (
            session.query(PaymentOperation).filter_by(payment_id=UUID(first.json()["id"])).count()
            == 1
        )


def test_foreign_key_conflicts_before_authorized_payment_noop(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    first = booking_scenario(client, airports, confirm=False)
    foreign_key = new_key()
    assert (
        _initiate(_customer_for(client, first), first["booking"]["id"], foreign_key).status_code
        == 200
    )
    second = booking_scenario(client, airports, confirm=False)
    second_customer = _customer_for(client, second)
    initial = _initiate(second_customer, second["booking"]["id"], new_key())
    before = initial.json()
    collision = _initiate(second_customer, second["booking"]["id"], foreign_key)
    assert collision.status_code == 409
    assert collision.json()["error"]["code"] == "idempotency_conflict"
    with SessionLocal() as session:
        payment = session.get(Payment, UUID(before["id"]))
        assert payment is not None and payment.status.value == "AUTHORIZED"
        assert len(payment.operations) == 1


def test_foreign_key_conflicts_before_creating_payment(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    first = booking_scenario(client, airports, confirm=False)
    foreign_key = new_key()
    assert (
        _initiate(_customer_for(client, first), first["booking"]["id"], foreign_key).status_code
        == 200
    )
    second = booking_scenario(client, airports, confirm=False)
    collision = _initiate(_customer_for(client, second), second["booking"]["id"], foreign_key)
    assert collision.status_code == 409
    assert collision.json()["error"]["code"] == "idempotency_conflict"
    with SessionLocal() as session:
        assert (
            session.query(Payment).filter_by(booking_id=UUID(second["booking"]["id"])).count() == 0
        )
    assert (
        client.get(f"/api/v1/trip-requests/{second['trip']['id']}").json()["status"] == "SUBMITTED"
    )
    assert client.get(f"/api/v1/offers/{second['offer']['id']}").json()["status"] == "SELECTED"
    assert (
        client.get(f"/api/v1/bookings/{second['booking']['id']}").json()["status"]
        == "PENDING_OPERATOR_CONFIRMATION"
    )


@pytest.mark.parametrize("terminal", ["CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED"])
def test_foreign_key_conflicts_before_terminal_payment_noop(
    client: TestClient, airports: list[dict[str, Any]], terminal: str
) -> None:
    owner = booking_scenario(client, airports, confirm=False)
    foreign_key = new_key()
    assert (
        _initiate(_customer_for(client, owner), owner["booking"]["id"], foreign_key).status_code
        == 200
    )
    target = booking_scenario(client, airports, confirm=True)
    target_customer = _customer_for(client, target)
    authorized = _initiate(target_customer, target["booking"]["id"], new_key()).json()
    captured = capture(client, authorized["id"]).json()
    if terminal == "PARTIALLY_REFUNDED":
        refund(client, authorized["id"], 1)
    elif terminal == "REFUNDED":
        refund(client, authorized["id"], captured["captured_amount_minor"])
    before = client.get(f"/api/v1/payments/{authorized['id']}").json()
    assert before["status"] == terminal
    collision = _initiate(target_customer, target["booking"]["id"], foreign_key)
    assert collision.status_code == 409
    assert collision.json()["error"]["code"] == "idempotency_conflict"
    after = client.get(f"/api/v1/payments/{authorized['id']}").json()
    assert after["status"] == before["status"]
    assert after["captured_amount_minor"] == before["captured_amount_minor"]
    assert after["refunded_amount_minor"] == before["refunded_amount_minor"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_minor", 1),
        ("currency", "USD"),
        ("provider", "STRIPE"),
        ("customer_id", "x"),
        ("capture", True),
    ],
)
def test_request_rejects_customer_authority_fields(
    client: TestClient, airports: list[dict[str, Any]], field: str, value: object
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    customer = _customer_for(client, scenario)
    response = customer.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/payment/initiate",
        json={"idempotency_key": f"customer-{uuid4()}", field: value},
    )
    assert response.status_code == 422
    assert client.get(f"/api/v1/bookings/{scenario['booking']['id']}/payment").status_code == 404


def test_foreign_customer_and_operator_cannot_initiate(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    foreign_id = iam_support.create_customer(client)
    foreign, foreign_org = iam_support.customer_owner_client(client, foreign_id)
    foreign.headers["X-Organization-Id"] = str(foreign_org)
    operator, _ = iam_support.operator_role_client(
        UUID(scenario["operator"]["id"]), OrganizationRole.OPERATOR_ADMIN
    )
    path = f"/api/v1/bookings/{scenario['booking']['id']}/payment/initiate"
    body = {"idempotency_key": f"customer-{uuid4()}"}
    assert foreign.post(path, json=body).status_code == 404
    assert operator.post(path, json=body).status_code == 403
    assert client.get(f"/api/v1/bookings/{scenario['booking']['id']}/payment").status_code == 404


def test_rejected_booking_fails_closed(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "OTHER"},
    )
    response = _initiate(
        _customer_for(client, scenario), scenario["booking"]["id"], f"customer-{uuid4()}"
    )
    assert response.status_code == 409


def test_confirmed_booking_and_customer_assistant_are_allowed(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=True)
    _owner, org_id = iam_support.customer_owner_client(client, UUID(scenario["customer"]["id"]))
    assistant = iam_support.member_client_for_org(org_id, OrganizationRole.CUSTOMER_ASSISTANT)
    assistant.headers["X-Organization-Id"] = str(org_id)
    response = _initiate(assistant, scenario["booking"]["id"], f"customer-{uuid4()}")
    assert response.status_code == 200
    assert response.json()["status"] == "AUTHORIZED"


def test_cancelled_booking_and_anonymous_principal_fail_closed(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    path = f"/api/v1/bookings/{scenario['booking']['id']}/payment/initiate"
    assert (
        iam_support.new_client()
        .post(path, json={"idempotency_key": f"customer-{uuid4()}"})
        .status_code
        == 401
    )
    client.post(f"/api/v1/bookings/{scenario['booking']['id']}/cancel", json={"actor": "CUSTOMER"})
    response = _initiate(
        _customer_for(client, scenario), scenario["booking"]["id"], f"customer-{uuid4()}"
    )
    assert response.status_code == 409


def test_openapi_contract_is_minimal_and_customer_safe(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/bookings/{booking_id}/payment/initiate"
    ]["post"]
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    request_name = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].split(
        "/"
    )[-1]
    response_name = operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].split("/")[-1]
    assert set(schemas[request_name]["properties"]) == {"idempotency_key"}
    assert schemas[request_name]["additionalProperties"] is False
    assert set(schemas[response_name]["properties"]) == SAFE_KEYS
