from __future__ import annotations

from collections.abc import Iterator

import pytest

from sky_bridge_jet.main import app


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()
