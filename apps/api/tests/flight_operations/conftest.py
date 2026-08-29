from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.core_aviation.seed import seed_airports


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    test_client = iam_support.integration_client()
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture(scope="module")
def airports(client: TestClient) -> list[dict[str, Any]]:
    if os.getenv("RUN_DATABASE_INTEGRATION") != "1":
        pytest.skip("set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available")
    with SessionLocal() as session:
        seed_airports(session)
    return client.get("/api/v1/airports").json()
