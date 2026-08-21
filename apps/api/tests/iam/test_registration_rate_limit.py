"""Phase 9.2.A — registration abuse protection.

Registration performs Argon2 hashing and a persistent write for an anonymous caller,
so it is protected by a conservative per-IP fixed-window limiter (5/60s). These tests
prove the floor is enforced server-side, is keyed on IP (not email, so a denial leaks
nothing about any account), short-circuits *before* the expensive hash, and returns a
safe 429 envelope with no sensitive content.
"""

from __future__ import annotations

from uuid import uuid4

import iam_support

from sky_bridge_jet.modules.iam import services as iam_services

# Registration validates password and structure without touching the database, so these
# limiter tests do not require PostgreSQL: the limiter denies before any persistence.


def _email() -> str:
    return f"reg+{uuid4().hex[:10]}@example.com"


def test_registration_is_rate_limited_per_ip(monkeypatch) -> None:
    # Count Argon2 hashes to prove the limiter short-circuits before hashing work.
    calls = {"hash": 0}
    real_hash = iam_services.hash_password

    def _counting_hash(password: str) -> str:
        calls["hash"] += 1
        return real_hash(password)

    monkeypatch.setattr(iam_services, "hash_password", _counting_hash)

    client = iam_support.new_client()
    statuses = [
        client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": "CorrectHorse12"}
        ).status_code
        for _ in range(6)
    ]

    # The first five are admitted (they reach the service and hash); the sixth is denied
    # by the limiter before any hashing/persistence occurs.
    assert statuses[5] == 429
    assert calls["hash"] <= 5


def test_registration_limit_is_keyed_on_ip_not_email() -> None:
    # Every attempt uses a distinct email, yet the sixth from the same client IP is
    # denied — proving the bucket is keyed on IP, not email (so a denial reveals nothing
    # about whether any particular account exists).
    client = iam_support.new_client()
    last = 200
    for _ in range(6):
        last = client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": "CorrectHorse12"}
        ).status_code
    assert last == 429


def test_rate_limited_response_is_safe() -> None:
    client = iam_support.new_client()
    resp = None
    for _ in range(6):
        resp = client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": "CorrectHorse12"}
        )
    assert resp is not None
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "rate_limited"
    # No email/password/token or account-existence signal in the public error.
    serialized = resp.text.lower()
    for forbidden in ("password", "correcthorse", "@example.com", "token", "hash"):
        assert forbidden not in serialized
