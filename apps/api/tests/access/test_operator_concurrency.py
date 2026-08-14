"""Phase 9.0.A-2 (J) — operator ownership-sensitive concurrency (real PostgreSQL).

The booking row lock serializes concurrent operator decisions, and a denied
cross-operator actor never mutates state even when racing the owner.
"""

from __future__ import annotations

import os
import threading
from typing import Any
from uuid import UUID

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.modules.iam.domain import OrganizationRole

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


@requires_db
def test_concurrent_operator_confirms_transition_once(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    operator_id = s["operator_id"]
    # Two distinct staff of the SAME operator organization both attempt to confirm.
    client_a, org_id = iam_support.operator_role_client(
        UUID(operator_id), OrganizationRole.OPERATOR_ADMIN
    )
    client_b = iam_support.member_client_for_org(org_id, OrganizationRole.OPERATOR_ADMIN)
    barrier = threading.Barrier(2)
    outcomes: list[int] = []
    lock = threading.Lock()

    def _confirm(client: TestClient) -> None:
        barrier.wait()
        status = client.post(
            f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": operator_id}
        ).status_code
        with lock:
            outcomes.append(status)

    threads = [
        threading.Thread(target=_confirm, args=(client_a,)),
        threading.Thread(target=_confirm, args=(client_b,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == [200, 409]  # exactly one confirmation wins
    assert admin.get(f"/api/v1/bookings/{s['booking_id']}").json()["status"] == "CONFIRMED"


@requires_db
def test_cross_operator_cannot_race_a_confirmation(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    owner_client, _ = iam_support.operator_role_client(
        UUID(s["operator_id"]), OrganizationRole.OPERATOR_ADMIN
    )
    intruder_client, _ = iam_support.operator_role_client(
        UUID(str(iam_support.create_operator(admin))), OrganizationRole.OPERATOR_ADMIN
    )
    barrier = threading.Barrier(2)
    results: dict[str, int] = {}
    lock = threading.Lock()

    def _act(name: str, client: TestClient, operator_id: str) -> None:
        barrier.wait()
        status = client.post(
            f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": operator_id}
        ).status_code
        with lock:
            results[name] = status

    threads = [
        threading.Thread(target=_act, args=("owner", owner_client, s["operator_id"])),
        threading.Thread(
            target=_act, args=("intruder", intruder_client, str(iam_support.create_operator(admin)))
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results["owner"] == 200  # the owner confirms
    assert results["intruder"] == 404  # the foreign operator is always concealed
    final: dict[str, Any] = admin.get(f"/api/v1/bookings/{s['booking_id']}").json()
    assert final["status"] == "CONFIRMED"
    assert final["operator_id"] == s["operator_id"]  # never the intruder
