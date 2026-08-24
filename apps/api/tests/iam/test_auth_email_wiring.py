"""Wiring of the auth-email seam into register / verification-resend (Phase 9.2.B1).

DB-backed. A shared ``FakeAuthEmailSender`` is injected via a dependency override so we
can assert exactly what was (or was not) sent. Proves: send happens after the durable
commit; the raw token reaches the sender but never the HTTP body; resend sends only for
an eligible pending account and stays enumeration-safe; and a provider failure changes
neither the registration outcome nor the resend acknowledgement. No real network occurs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import iam_support
import pytest

from sky_bridge_jet.core.auth_email import (
    AuthEmailError,
    AuthEmailErrorCategory,
    FakeAuthEmailSender,
)
from sky_bridge_jet.main import app
from sky_bridge_jet.modules.iam.dependencies import get_auth_email_sender

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


class _ExplodingSender:
    """Sender that always fails, to prove failures are swallowed post-commit."""

    def send_verification_email(self, message: object) -> None:
        raise AuthEmailError(AuthEmailErrorCategory.PROVIDER_UNAVAILABLE)


@pytest.fixture
def fake_sender() -> Iterator[FakeAuthEmailSender]:
    sender = FakeAuthEmailSender()
    app.dependency_overrides[get_auth_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_auth_email_sender, None)


def _email() -> str:
    return f"b1+{uuid4().hex[:10]}@example.com"


@requires_db
def test_register_sends_one_verification_email_with_fragment_link(fake_sender) -> None:
    client = iam_support.new_client()
    email = _email()
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    assert reg.status_code == 201, reg.text

    assert len(fake_sender.sent) == 1
    message = fake_sender.sent[0]
    assert message.to == email
    assert message.subject == "Verify your Sky Bridge Jet email"
    # The raw token is delivered to the sender via the fragment link...
    dev_token = reg.json()["verification_token"]  # dev affordance (non-production)
    assert dev_token is not None
    assert f"/verify-email#token={dev_token}" in message.text_body
    assert "24 hours" in message.text_body
    # ...and using that emailed token actually verifies the account.
    assert client.post("/api/v1/auth/verify-email", json={"token": dev_token}).status_code == 200


@requires_db
def test_register_response_never_contains_raw_token_in_production(monkeypatch, fake_sender) -> None:
    monkeypatch.setattr(
        "sky_bridge_jet.modules.iam.router._dev_token", lambda settings, token: None
    )
    client = iam_support.new_client()
    reg = client.post(
        "/api/v1/auth/register", json={"email": _email(), "password": "CorrectHorse12"}
    )
    assert reg.status_code == 201
    assert reg.json()["verification_token"] is None
    # The token still reached the mailer even though the HTTP response hides it.
    assert len(fake_sender.sent) == 1
    assert "/verify-email#token=" in fake_sender.sent[0].text_body


@requires_db
def test_register_succeeds_even_when_provider_fails() -> None:
    exploding = _ExplodingSender()
    app.dependency_overrides[get_auth_email_sender] = lambda: exploding
    try:
        client = iam_support.new_client()
        email = _email()
        reg = client.post(
            "/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"}
        )
        # Registration is durable regardless of delivery failure...
        assert reg.status_code == 201
        # ...and the account can still be verified with its dev token.
        token = reg.json()["verification_token"]
        assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    finally:
        app.dependency_overrides.pop(get_auth_email_sender, None)


@requires_db
def test_resend_sends_only_for_eligible_pending_account(fake_sender) -> None:
    client = iam_support.new_client()
    email = _email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    fake_sender.sent.clear()  # ignore the registration send

    # Eligible pending account → exactly one send, uniform acknowledgement.
    resp = client.post("/api/v1/auth/verification/resend", json={"email": email})
    assert resp.status_code == 200
    assert len(fake_sender.sent) == 1
    assert fake_sender.sent[0].to == email


@requires_db
def test_resend_sends_nothing_for_ineligible_but_response_is_identical(fake_sender) -> None:
    client = iam_support.new_client()
    unknown = client.post("/api/v1/auth/verification/resend", json={"email": _email()})
    malformed = client.post("/api/v1/auth/verification/resend", json={"email": "not-an-email"})
    assert unknown.status_code == malformed.status_code == 200
    assert (
        unknown.json()["message"]
        == malformed.json()["message"]
        == "If the account requires verification, verification instructions have been sent"
    )
    assert fake_sender.sent == []  # no send for unknown/malformed


@requires_db
def test_resend_acknowledgement_unchanged_when_provider_fails() -> None:
    exploding = _ExplodingSender()
    app.dependency_overrides[get_auth_email_sender] = lambda: exploding
    try:
        client = iam_support.new_client()
        email = _email()
        client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
        resp = client.post("/api/v1/auth/verification/resend", json={"email": email})
        assert resp.status_code == 200
        assert (
            resp.json()["message"]
            == "If the account requires verification, verification instructions have been sent"
        )
    finally:
        app.dependency_overrides.pop(get_auth_email_sender, None)
