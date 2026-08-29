import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.main import app


class AvailableSession:
    def execute(self, _statement: object) -> None:
        return None

    def scalar(self, _statement: object) -> str:
        return "20260901_0015"


class UnavailableSession:
    def execute(self, _statement: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_ready_returns_ok_when_database_is_reachable(client: TestClient) -> None:
    def available_db() -> Generator[AvailableSession, None, None]:
        yield AvailableSession()

    app.dependency_overrides[get_db] = available_db
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_service_unavailable_when_database_cannot_be_reached(
    client: TestClient,
) -> None:
    def unavailable_db() -> Generator[UnavailableSession, None, None]:
        yield UnavailableSession()

    app.dependency_overrides[get_db] = unavailable_db
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": {"status": "unavailable"}}


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_ready_uses_the_configured_postgresql_database(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
