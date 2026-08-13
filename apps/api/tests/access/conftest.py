from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.main import app
from sky_bridge_jet.modules.core_aviation.seed import seed_airports


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def admin() -> TestClient:
    if os.getenv("RUN_DATABASE_INTEGRATION") != "1":
        pytest.skip("set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available")
    return iam_support.product_owner_client()


@pytest.fixture(scope="module")
def airports(admin: TestClient) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        seed_airports(session)
    return admin.get("/api/v1/airports").json()
