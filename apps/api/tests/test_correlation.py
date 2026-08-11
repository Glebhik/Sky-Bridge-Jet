import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.core.correlation import (
    MAX_CORRELATION_ID_LENGTH,
    sanitize_correlation_id,
)
from sky_bridge_jet.core.logging import JsonFormatter
from sky_bridge_jet.main import app

_UUID_PATTERN = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_PRIVATE_EMAIL = "phase2-private-customer@example.com"


def _is_generated(value: str) -> bool:
    return _UUID_PATTERN.match(value) is not None


def test_valid_client_id_is_preserved() -> None:
    valid = "trace-1234_ABC.def"
    assert sanitize_correlation_id(valid) == valid


def test_uuid_client_id_is_preserved() -> None:
    value = str(uuid.uuid4())
    assert sanitize_correlation_id(value) == value


def test_value_at_maximum_length_is_preserved() -> None:
    at_limit = "a" * MAX_CORRELATION_ID_LENGTH
    assert sanitize_correlation_id(at_limit) == at_limit


def test_missing_value_is_replaced_with_generated_id() -> None:
    assert _is_generated(sanitize_correlation_id(None))


@pytest.mark.parametrize(
    "unsafe",
    [
        _PRIVATE_EMAIL,
        "Bearer sk-live-super-secret-token",
        "id with spaces",
        "path/../traversal",
        "value\nwith-newline",
        "sql'injection--",
    ],
)
def test_unsafe_values_are_replaced_with_generated_id(unsafe: str) -> None:
    generated = sanitize_correlation_id(unsafe)
    assert generated != unsafe
    assert _is_generated(generated)


def test_overlong_value_is_replaced_with_generated_id() -> None:
    overlong = "a" * (MAX_CORRELATION_ID_LENGTH + 1)
    generated = sanitize_correlation_id(overlong)
    assert generated != overlong
    assert _is_generated(generated)


def test_pii_request_id_header_never_reaches_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="sky_bridge_jet.main")
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": _PRIVATE_EMAIL})

    assert response.status_code == 200
    # The echoed header is a safe generated ID, not the client-supplied PII.
    assert _is_generated(response.headers["x-request-id"])
    assert response.headers["x-request-id"] != _PRIVATE_EMAIL

    request_records = [r for r in caplog.records if r.getMessage() == "request_completed"]
    assert request_records, "expected a request_completed log record"
    # Render through the real structured formatter, which includes correlation_id.
    rendered = "\n".join(JsonFormatter().format(record) for record in request_records)
    assert _PRIVATE_EMAIL not in rendered
    assert _PRIVATE_EMAIL not in caplog.text


def test_valid_request_id_header_is_preserved_for_tracing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    valid = "trace-abc123"
    caplog.set_level(logging.INFO, logger="sky_bridge_jet.main")
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": valid})

    assert response.headers["x-request-id"] == valid
    assert any(getattr(record, "correlation_id", None) == valid for record in caplog.records)
