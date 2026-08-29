from __future__ import annotations

from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from offers._support import create_aircraft, offer_payload
from sqlalchemy import delete, event, select, text

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.core_aviation.seed import seed_airports
from sky_bridge_jet.modules.iam.domain import OrganizationRole, OrganizationType
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership
from sky_bridge_jet.modules.pilot_governance.domain import PilotAccessDeniedError, PilotMode
from sky_bridge_jet.modules.pilot_governance.models import (
    PILOT_GOVERNANCE_SINGLETON_ID,
    PilotGovernanceAudit,
    PilotGovernanceState,
    PilotParticipant,
)
from sky_bridge_jet.modules.pilot_governance.services import (
    PilotAccessService,
    PilotGovernanceService,
)

pytestmark = pytest.mark.skipif(
    __import__("os").getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="requires disposable PostgreSQL",
)


def _reset() -> None:
    with SessionLocal.begin() as session:
        session.execute(delete(PilotGovernanceAudit))
        session.execute(delete(PilotParticipant))
        state = session.get(PilotGovernanceState, PILOT_GOVERNANCE_SINGLETON_ID)
        assert state is not None
        state.mode = PilotMode.INTERNAL_ONLY
        state.payment_initiation_enabled = False
        state.version += 1


def _invite_and_set(admin: TestClient, organization_id: UUID, status: str) -> dict:
    invited = admin.post(
        "/api/v1/platform/pilot/participants",
        json={"organization_id": str(organization_id), "reason": "PILOT_INVITATION"},
    )
    assert invited.status_code == 201, invited.text
    row = invited.json()
    if status != "INVITED":
        changed = admin.post(
            f"/api/v1/platform/pilot/participants/{row['id']}/status",
            json={
                "status": status,
                "expected_version": row["version"],
                "reason": "OWNER_APPROVED",
            },
        )
        assert changed.status_code == 200, changed.text
        row = changed.json()
    return row


def _platform_organization_id(user_id: UUID) -> UUID:
    with SessionLocal() as session:
        organization_id = session.scalar(
            select(OrganizationMembership.organization_id)
            .join(Organization)
            .where(
                OrganizationMembership.user_id == user_id,
                Organization.organization_type == OrganizationType.PLATFORM,
            )
        )
    assert organization_id is not None
    return organization_id


def test_platform_authority_state_machine_audit_and_safe_projection(client: TestClient) -> None:
    _reset()
    admin = iam_support.product_owner_client()
    support = iam_support.platform_role_client(OrganizationRole.PLATFORM_SUPPORT)
    operator = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    customer_id = iam_support.create_customer(admin)
    customer, organization_id = iam_support.customer_owner_client(admin, customer_id)
    try:
        state = admin.get("/api/v1/platform/pilot/state")
        assert state.status_code == 200
        assert state.json()["mode"] == "INTERNAL_ONLY"
        assert support.get("/api/v1/platform/pilot/state").status_code == 200
        assert operator.get("/api/v1/platform/pilot/state").status_code == 403
        assert (
            support.post(
                "/api/v1/platform/pilot/participants",
                json={"organization_id": str(organization_id)},
            ).status_code
            == 403
        )

        invited = admin.post(
            "/api/v1/platform/pilot/participants",
            json={"organization_id": str(organization_id), "reason": "PILOT_INVITATION"},
        )
        assert invited.status_code == 201, invited.text
        body = invited.json()
        assert body["status"] == "INVITED"
        assert body["participant_type"] == "CUSTOMER"
        assert "email" not in str(body).lower()
        duplicate = admin.post(
            "/api/v1/platform/pilot/participants",
            json={"organization_id": str(organization_id), "reason": "PILOT_INVITATION"},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == body["id"]

        active = admin.post(
            f"/api/v1/platform/pilot/participants/{body['id']}/status",
            json={
                "status": "ACTIVE",
                "expected_version": body["version"],
                "reason": "OWNER_APPROVED",
            },
        )
        assert active.status_code == 200
        assert active.json()["status"] == "ACTIVE"
        stale = admin.post(
            f"/api/v1/platform/pilot/participants/{body['id']}/status",
            json={
                "status": "SUSPENDED",
                "expected_version": body["version"],
                "reason": "MANUAL_REVIEW_REQUIRED",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "pilot_governance_conflict"
        events = admin.get("/api/v1/platform/pilot/audits", params={"limit": 20, "offset": 0})
        assert events.status_code == 200
        assert [row["action"] for row in events.json()] == ["ACTIVE", "INVITE"]
        assert (
            admin.get("/api/v1/platform/pilot/participants", params={"limit": 101}).status_code
            == 422
        )
    finally:
        customer.close()
        admin.close()
        support.close()
        operator.close()
        _reset()


def test_controlled_mode_requires_active_exact_organization_and_pause_fails_closed(
    client: TestClient,
) -> None:
    _reset()
    admin = iam_support.product_owner_client()
    customer_id = iam_support.create_customer(admin)
    customer, organization_id = iam_support.customer_owner_client(admin, customer_id)
    foreign_id = iam_support.create_customer(admin)
    foreign, foreign_org = iam_support.customer_owner_client(admin, foreign_id)
    try:
        state = admin.get("/api/v1/platform/pilot/state").json()
        changed = admin.post(
            "/api/v1/platform/pilot/state",
            json={
                "mode": "CONTROLLED_EXTERNAL",
                "payment_initiation_enabled": False,
                "expected_version": state["version"],
                "reason": "OWNER_APPROVED",
            },
        )
        assert changed.status_code == 200
        with SessionLocal() as session, pytest.raises(PilotAccessDeniedError):
            PilotAccessService(session).require_customer(customer_id)
        invited = admin.post(
            "/api/v1/platform/pilot/participants",
            json={"organization_id": str(organization_id), "reason": "PILOT_INVITATION"},
        ).json()
        active = admin.post(
            f"/api/v1/platform/pilot/participants/{invited['id']}/status",
            json={
                "status": "ACTIVE",
                "expected_version": invited["version"],
                "reason": "OWNER_APPROVED",
            },
        )
        assert active.status_code == 200
        with SessionLocal() as session:
            PilotAccessService(session).require_customer(customer_id)
        with SessionLocal() as session, pytest.raises(PilotAccessDeniedError):
            PilotAccessService(session).require_customer(foreign_id)
        current = admin.get("/api/v1/platform/pilot/state").json()
        paused = admin.post(
            "/api/v1/platform/pilot/state",
            json={
                "mode": "PAUSED",
                "payment_initiation_enabled": False,
                "expected_version": current["version"],
                "reason": "OPERATIONAL_PAUSE",
            },
        )
        assert paused.status_code == 200
        with SessionLocal() as session, pytest.raises(PilotAccessDeniedError):
            PilotAccessService(session).require_customer(customer_id)
        assert admin.get("/api/v1/platform/pilot/audits").status_code == 200
    finally:
        customer.close()
        foreign.close()
        admin.close()
        _reset()


def test_operator_and_financial_switch_matrix_is_independent_and_fail_closed(
    client: TestClient,
) -> None:
    _reset()
    admin = iam_support.product_owner_client()
    operator_id = iam_support.create_operator(admin)
    operator, operator_org = iam_support.operator_role_client(
        operator_id, OrganizationRole.OPERATOR_ADMIN
    )
    customer_id = iam_support.create_customer(admin)
    customer, customer_org = iam_support.customer_owner_client(admin, customer_id)
    try:
        state = admin.get("/api/v1/platform/pilot/state").json()
        controlled = admin.post(
            "/api/v1/platform/pilot/state",
            json={
                "mode": "CONTROLLED_EXTERNAL",
                "payment_initiation_enabled": False,
                "expected_version": state["version"],
                "reason": "OWNER_APPROVED",
            },
        ).json()
        for organization_id in (operator_org, customer_org):
            invited = admin.post(
                "/api/v1/platform/pilot/participants",
                json={"organization_id": str(organization_id), "reason": "PILOT_INVITATION"},
            ).json()
            activated = admin.post(
                f"/api/v1/platform/pilot/participants/{invited['id']}/status",
                json={
                    "status": "ACTIVE",
                    "expected_version": invited["version"],
                    "reason": "OWNER_APPROVED",
                },
            )
            assert activated.status_code == 200
        with SessionLocal() as session:
            gate = PilotAccessService(session)
            gate.require_operator(operator_id)
            gate.require_customer(customer_id)
            with pytest.raises(PilotAccessDeniedError):
                gate.require_payment_initiation(customer_id)
        enabled = admin.post(
            "/api/v1/platform/pilot/state",
            json={
                "mode": "CONTROLLED_EXTERNAL",
                "payment_initiation_enabled": True,
                "expected_version": controlled["version"],
                "reason": "OWNER_APPROVED",
            },
        )
        assert enabled.status_code == 200
        with SessionLocal() as session:
            PilotAccessService(session).require_payment_initiation(customer_id)
    finally:
        operator.close()
        customer.close()
        admin.close()
        _reset()


def test_default_participant_listing_uses_bounded_ordering_index_at_scale() -> None:
    """Lock the production default ordering to an index-backed bounded plan."""
    _reset()
    marker = "plan-regression-"
    try:
        with SessionLocal.begin() as session:
            session.execute(
                text(
                    """
                    INSERT INTO organizations
                        (id, organization_type, display_name, created_at, updated_at)
                    SELECT md5(:marker || g::text)::uuid,
                           'CUSTOMER'::organization_type,
                           :marker || g::text,
                           '2026-08-29 12:00:00+00'::timestamptz,
                           '2026-08-29 12:00:00+00'::timestamptz
                    FROM generate_series(1, 5000) AS g
                    """
                ),
                {"marker": marker},
            )
            session.execute(
                text(
                    """
                    INSERT INTO pilot_participants
                        (id, organization_id, participant_type, status, version,
                         created_at, updated_at)
                    SELECT md5('participant-' || g::text)::uuid,
                           md5(:marker || g::text)::uuid,
                           'CUSTOMER'::pilot_participant_type,
                           'ACTIVE'::pilot_participant_status,
                           1,
                           '2026-08-29 12:00:00+00'::timestamptz,
                           '2026-08-29 12:00:00+00'::timestamptz
                    FROM generate_series(1, 5000) AS g
                    """
                ),
                {"marker": marker},
            )
            session.execute(text("ANALYZE pilot_participants"))
            connection = session.connection()
            query_count = 0

            def count_query(*_args: object) -> None:
                nonlocal query_count
                query_count += 1

            event.listen(connection, "before_cursor_execute", count_query)
            service = PilotGovernanceService(session)
            for limit in (1, 20, 100):
                before = query_count
                assert len(service.list_participants(limit=limit, offset=0)) == limit
                assert query_count - before == 1
            first = service.list_participants(limit=100, offset=0)
            second = service.list_participants(limit=100, offset=100)
            assert len(first) == len(second) == 100
            assert {row[0].id for row in first}.isdisjoint(row[0].id for row in second)
            first_ids = [row[0].id for row in first]
            assert first_ids == sorted(first_ids)
            assert [
                row[0].id for row in service.list_participants(limit=100, offset=0)
            ] == first_ids
            event.remove(connection, "before_cursor_execute", count_query)

            plan = session.execute(
                text(
                    """
                    EXPLAIN (FORMAT JSON)
                    SELECT p.id, o.display_name
                    FROM pilot_participants AS p
                    JOIN organizations AS o ON o.id = p.organization_id
                    ORDER BY p.created_at, p.id
                    LIMIT 20 OFFSET 0
                    """
                )
            ).scalar_one()[0]["Plan"]

            def nodes(node: dict[str, object]) -> list[dict[str, object]]:
                children = node.get("Plans", [])
                assert isinstance(children, list)
                return [node, *(child for item in children for child in nodes(item))]

            plan_nodes = nodes(plan)
            assert any(
                node.get("Index Name") == "ix_pilot_participants_created_id" for node in plan_nodes
            )
            assert not any(node.get("Node Type") == "Sort" for node in plan_nodes)
            assert not any(
                node.get("Node Type") == "Seq Scan"
                and node.get("Relation Name") == "pilot_participants"
                for node in plan_nodes
            )
    finally:
        _reset()
        with SessionLocal.begin() as session:
            session.execute(
                text("DELETE FROM organizations WHERE display_name LIKE :marker"),
                {"marker": f"{marker}%"},
            )


def test_active_organization_binds_customer_and_operator_mutations(client: TestClient) -> None:
    """A non-selected membership can never lend authority to the active tenant."""
    _reset()
    with SessionLocal.begin() as session:
        seed_airports(session)
    admin = iam_support.product_owner_client()
    customer_actor = iam_support.new_client()
    operator_actor = iam_support.new_client()
    customer_orgs: dict[str, UUID] = {}
    operator_orgs: dict[str, UUID] = {}
    try:
        airports = admin.get("/api/v1/airports").json()
        customer_a = iam_support.create_customer(admin)
        customer_b = iam_support.create_customer(admin)

        def grant_customers(user_id: UUID) -> None:
            for label, customer_id in (("a", customer_a), ("b", customer_b)):
                customer_orgs[label] = iam_support._grant_membership(
                    user_id,
                    organization_type=OrganizationType.CUSTOMER,
                    role=OrganizationRole.CUSTOMER_OWNER,
                    customer_id=customer_id,
                    display_name=f"Active-org customer {label}",
                )

        iam_support.register_verify_login(customer_actor, before_verify=grant_customers)
        _invite_and_set(admin, customer_orgs["a"], "ACTIVE")
        suspended_customer = _invite_and_set(admin, customer_orgs["b"], "ACTIVE")
        suspended = admin.post(
            f"/api/v1/platform/pilot/participants/{suspended_customer['id']}/status",
            json={
                "status": "SUSPENDED",
                "expected_version": suspended_customer["version"],
                "reason": "MANUAL_REVIEW_REQUIRED",
            },
        )
        assert suspended.status_code == 200, suspended.text
        state = admin.get("/api/v1/platform/pilot/state").json()
        enabled = admin.post(
            "/api/v1/platform/pilot/state",
            json={
                "mode": "CONTROLLED_EXTERNAL",
                "payment_initiation_enabled": False,
                "expected_version": state["version"],
                "reason": "OWNER_APPROVED",
            },
        )
        assert enabled.status_code == 200, enabled.text
        draft = admin.post(
            "/api/v1/trip-requests",
            json={
                "customer_id": str(customer_a),
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
        submit_path = f"/api/v1/trip-requests/{draft['id']}/submit"
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["b"])
        assert (
            customer_actor.post(
                submit_path, json={"expected_version": draft["version"]}
            ).status_code
            == 404
        )
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["a"])
        submitted = customer_actor.post(submit_path, json={"expected_version": draft["version"]})
        assert submitted.status_code == 200, submitted.text

        operator_a = iam_support.create_operator(admin)
        operator_b = iam_support.create_operator(admin)

        def grant_operators(user_id: UUID) -> None:
            for label, operator_id in (("a", operator_a), ("b", operator_b)):
                operator_orgs[label] = iam_support._grant_membership(
                    user_id,
                    organization_type=OrganizationType.OPERATOR,
                    role=OrganizationRole.OPERATOR_ADMIN,
                    operator_id=operator_id,
                    display_name=f"Active-org operator {label}",
                )

        iam_support.register_verify_login(operator_actor, before_verify=grant_operators)
        _invite_and_set(admin, operator_orgs["a"], "ACTIVE")
        _invite_and_set(admin, operator_orgs["b"], "ACTIVE")
        aircraft = create_aircraft(admin, str(operator_a))
        offer_response = admin.post(
            "/api/v1/offers",
            json=offer_payload(
                trip_request_id=draft["id"],
                operator_id=str(operator_a),
                aircraft_id=aircraft["id"],
            ),
        )
        assert offer_response.status_code == 201, offer_response.text
        offer = offer_response.json()
        operator_actor.headers["X-Organization-Id"] = str(operator_orgs["b"])
        assert (
            operator_actor.patch(
                f"/api/v1/offers/{offer['id']}", json={"operator_amount_minor": 900_000}
            ).status_code
            == 404
        )
        assert operator_actor.post(f"/api/v1/offers/{offer['id']}/submit").status_code == 404
        operator_actor.headers["X-Organization-Id"] = str(operator_orgs["a"])
        updated = operator_actor.patch(
            f"/api/v1/offers/{offer['id']}", json={"operator_amount_minor": 900_000}
        )
        assert updated.status_code == 200, updated.text
        submitted_offer = operator_actor.post(f"/api/v1/offers/{offer['id']}/submit")
        assert submitted_offer.status_code == 200, submitted_offer.text

        select_path = f"/api/v1/trip-requests/{draft['id']}/offers/{offer['id']}/select"
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["b"])
        assert customer_actor.post(select_path).status_code == 404
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["a"])
        assert customer_actor.post(select_path).status_code == 200
        booking_body = {"trip_request_id": draft["id"], "operator_offer_id": offer["id"]}
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["b"])
        assert customer_actor.post("/api/v1/bookings", json=booking_body).status_code == 404
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["a"])
        booking_response = customer_actor.post("/api/v1/bookings", json=booking_body)
        assert booking_response.status_code == 201, booking_response.text
        booking = booking_response.json()
        customer_actor.headers["X-Organization-Id"] = str(customer_orgs["b"])
        assert (
            customer_actor.post(
                f"/api/v1/bookings/{booking['id']}/payment/initiate",
                json={"idempotency_key": f"active-org-{uuid4()}"},
            ).status_code
            == 404
        )

        operator_actor.headers["X-Organization-Id"] = str(operator_orgs["b"])
        assert (
            operator_actor.post(f"/api/v1/bookings/{booking['id']}/confirm", json={}).status_code
            == 404
        )
        assert (
            operator_actor.post(
                f"/api/v1/bookings/{booking['id']}/reject", json={"reason": "OTHER"}
            ).status_code
            == 404
        )
        operator_actor.headers["X-Organization-Id"] = str(operator_orgs["a"])
        assert (
            operator_actor.post(f"/api/v1/bookings/{booking['id']}/confirm", json={}).status_code
            == 200
        )
    finally:
        admin.close()
        customer_actor.close()
        operator_actor.close()
        _reset()


def test_platform_pilot_authority_is_bound_to_active_platform_context(client: TestClient) -> None:
    _reset()
    admin, admin_user = iam_support.product_owner_client_with_user()
    support = iam_support.new_client()
    customer_id = iam_support.create_customer(admin)
    customer, customer_org = iam_support.customer_owner_client(admin, customer_id)
    support_ids: dict[str, UUID] = {}

    def grant_support(user_id: UUID) -> None:
        support_ids["platform"] = iam_support._grant_membership(
            user_id,
            organization_type=OrganizationType.PLATFORM,
            role=OrganizationRole.PLATFORM_SUPPORT,
            display_name="Active-org support platform",
        )
        with SessionLocal.begin() as session:
            session.add(
                OrganizationMembership(
                    user_id=user_id,
                    organization_id=customer_org,
                    role=OrganizationRole.CUSTOMER_OWNER,
                )
            )

    iam_support.register_verify_login(support, before_verify=grant_support)
    platform_org = _platform_organization_id(admin_user)
    with SessionLocal.begin() as session:
        session.add(
            OrganizationMembership(
                user_id=admin_user,
                organization_id=customer_org,
                role=OrganizationRole.CUSTOMER_OWNER,
            )
        )
    try:
        admin.headers["X-Organization-Id"] = str(platform_org)
        assert admin.get("/api/v1/platform/pilot/participants").status_code == 200
        admin.headers["X-Organization-Id"] = str(customer_org)
        for method, path, body in (
            ("get", "/api/v1/platform/pilot/participants", None),
            ("post", "/api/v1/platform/pilot/participants", {"organization_id": str(customer_org)}),
            (
                "post",
                "/api/v1/platform/pilot/participants/00000000-0000-0000-0000-000000000001/status",
                {"status": "ACTIVE", "expected_version": 1, "reason": "OWNER_APPROVED"},
            ),
            (
                "post",
                "/api/v1/platform/pilot/state",
                {
                    "mode": "PAUSED",
                    "payment_initiation_enabled": False,
                    "expected_version": 1,
                    "reason": "OWNER_APPROVED",
                },
            ),
        ):
            assert admin.request(method, path, json=body).status_code == 403
        admin.headers["X-Organization-Id"] = str(platform_org)
        assert admin.get("/api/v1/platform/pilot/state").status_code == 200

        support.headers["X-Organization-Id"] = str(support_ids["platform"])
        support_state = support.get("/api/v1/platform/pilot/state")
        assert support_state.status_code == 200
        assert (
            support.post(
                "/api/v1/platform/pilot/state",
                json={
                    "mode": "PAUSED",
                    "payment_initiation_enabled": False,
                    "expected_version": support_state.json()["version"],
                    "reason": "OWNER_APPROVED",
                },
            ).status_code
            == 403
        )
        support.headers["X-Organization-Id"] = str(customer_org)
        assert support.get("/api/v1/platform/pilot/state").status_code == 403
    finally:
        admin.close()
        support.close()
        customer.close()
        _reset()
