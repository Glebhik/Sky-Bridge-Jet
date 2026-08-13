"""Concurrency: authorization holds and no lifecycle transition is bypassed when two
authorized customer principals act on the same resource simultaneously (real PG)."""

from __future__ import annotations

import os
import threading
from typing import Any

import iam_support
import pytest
from fastapi.testclient import TestClient

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


@requires_db
def test_concurrent_submit_of_same_trip_transitions_once(admin: TestClient, airports: list) -> None:
    from sky_bridge_jet.modules.iam.domain import OrganizationRole

    customer_id = iam_support.create_customer(admin)
    # Two distinct users, both CUSTOMER_OWNER of the SAME customer organization.
    client_one, org_id = iam_support.customer_owner_client(admin, customer_id)
    client_two = iam_support.member_client_for_org(org_id, OrganizationRole.CUSTOMER_OWNER)

    trip = client_one.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": str(customer_id),
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 1,
                }
            ],
        },
    ).json()
    trip_id = trip["id"]
    version = trip["version"]

    barrier = threading.Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def attempt(client: TestClient) -> None:
        barrier.wait()
        status = client.post(
            f"/api/v1/trip-requests/{trip_id}/submit", json={"expected_version": version}
        ).status_code
        with lock:
            results.append(status)

    threads = [
        threading.Thread(target=attempt, args=(client_one,)),
        threading.Thread(target=attempt, args=(client_two,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Exactly one authorized submit succeeds; the other is a safe lifecycle/concurrency
    # conflict — never a bypass, never a 5xx.
    assert sorted(results) == [200, 409], results
    final: dict[str, Any] = client_one.get(f"/api/v1/trip-requests/{trip_id}").json()
    assert final["status"] == "SUBMITTED"


@requires_db
def test_cross_tenant_actor_cannot_race_a_lifecycle_change(
    admin: TestClient, airports: list
) -> None:
    customer_id = iam_support.create_customer(admin)
    owner_client, _ = iam_support.customer_owner_client(admin, customer_id)
    intruder_client, _ = iam_support.customer_owner_client(
        admin, iam_support.create_customer(admin)
    )
    trip = owner_client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": str(customer_id),
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 1,
                }
            ],
        },
    ).json()
    trip_id = trip["id"]

    barrier = threading.Barrier(2)
    outcomes: dict[str, int] = {}
    lock = threading.Lock()

    def owner_submit() -> None:
        barrier.wait()
        code = owner_client.post(
            f"/api/v1/trip-requests/{trip_id}/submit", json={"expected_version": trip["version"]}
        ).status_code
        with lock:
            outcomes["owner"] = code

    def intruder_cancel() -> None:
        barrier.wait()
        code = intruder_client.post(
            f"/api/v1/trip-requests/{trip_id}/cancel", json={"expected_version": trip["version"]}
        ).status_code
        with lock:
            outcomes["intruder"] = code

    threads = [threading.Thread(target=owner_submit), threading.Thread(target=intruder_cancel)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # The intruder never affects the trip (404, concealed); the owner's action stands.
    assert outcomes["intruder"] == 404
    assert outcomes["owner"] == 200
