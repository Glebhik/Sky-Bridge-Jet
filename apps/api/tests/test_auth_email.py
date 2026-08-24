"""Unit tests for the provider-neutral auth-email seam (Phase 9.2.B1).

No network and no credentials: the Resend adapter's single HTTP call is exercised by
monkeypatching ``urllib.request.urlopen``. No test here calls the real Resend API.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from pydantic import ValidationError

from sky_bridge_jet.core import auth_email as auth_email_module
from sky_bridge_jet.core.auth_email import (
    AuthEmailError,
    AuthEmailErrorCategory,
    FakeAuthEmailSender,
    ResendAuthEmailSender,
    VerificationEmail,
    build_auth_email_sender,
)
from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.modules.iam.auth_email_content import (
    VERIFICATION_SUBJECT,
    build_verification_email,
    build_verification_url,
)


def _message() -> VerificationEmail:
    return VerificationEmail(
        to="person@example.com", subject="S", text_body="text", html_body="<p>html</p>"
    )


class _FakeHTTPResponse(io.BytesIO):
    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_fake_sender_records_messages_deterministically() -> None:
    sender = FakeAuthEmailSender()
    assert sender.sent == []
    m = _message()
    sender.send_verification_email(m)
    assert sender.sent == [m]


def test_build_sender_disabled_returns_fake() -> None:
    sender = build_auth_email_sender(Settings(auth_email_enabled=False))
    assert isinstance(sender, FakeAuthEmailSender)


def test_settings_enabled_without_key_fails_closed_without_echoing_key(monkeypatch) -> None:
    # Hermetic: ignore any ambient .env / OS key so we test the no-key path deterministically.
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        Settings(auth_email_enabled=True, _env_file=None)  # no resend_api_key
    text = str(excinfo.value).lower()
    assert "resend_api_key" in text or "required" in text
    # The message must never contain a key value or prefix.
    assert "re_" not in str(excinfo.value)


def test_web_public_origin_is_validated_and_normalized() -> None:
    assert Settings(web_public_origin="http://localhost:3000/").web_public_origin == (
        "http://localhost:3000"
    )
    for bad in ("ftp://h", "http://u:p@h", "http://h/path", "http://h?q=1", "nope"):
        with pytest.raises(ValidationError):
            Settings(web_public_origin=bad)


def test_verification_content_is_factual_and_uses_fragment_link() -> None:
    url = build_verification_url("http://localhost:3000", "RAWTOKEN123")
    assert url == "http://localhost:3000/verify-email#token=RAWTOKEN123"
    email = build_verification_email(
        recipient="p@example.com", verification_url=url, expires_in_hours=24
    )
    assert email.subject == VERIFICATION_SUBJECT == "Verify your Sky Bridge Jet email"
    for body in (email.text_body, email.html_body):
        assert "Sky Bridge Jet" in body
        assert url in body
        assert "24 hours" in body
        assert "did not create" in body
    # No tracking pixel / remote image / marketing.
    assert "<img" not in email.html_body
    assert "unsubscribe" not in email.html_body.lower()


def test_resend_adapter_success(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHTTPResponse(200, b'{"id": "abc123"}')

    monkeypatch.setattr(auth_email_module.urllib.request, "urlopen", _fake_urlopen)
    sender = ResendAuthEmailSender(
        "re_secret", "Sky Bridge Jet <no-reply@skybridgejet.disgroup.ie>"
    )
    sender.send_verification_email(_message())
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["method"] == "POST"
    headers = {k.lower(): v for k, v in captured["headers"].items()}  # type: ignore[union-attr]
    assert headers["authorization"] == "Bearer re_secret"
    assert headers["content-type"] == "application/json"
    body = captured["body"]
    assert body["from"].startswith("Sky Bridge Jet")  # type: ignore[index]
    assert body["to"] == ["person@example.com"]  # type: ignore[index]
    assert "text" in body and "html" in body  # type: ignore[operator]


def test_resend_adapter_sets_explicit_non_default_user_agent(monkeypatch) -> None:
    """Regression: `api.resend.com` is behind Cloudflare, which 403-blocks (error 1010)
    the stdlib default ``User-Agent: Python-urllib/x.y``. The adapter MUST send an explicit
    User-Agent so the request is not bot-blocked (the original defect surfaced as a
    misleading "credentials rejected" 403)."""
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):  # noqa: ANN001
        # get_header capitalizes the key: "User-Agent" -> "User-agent".
        captured["user_agent"] = request.get_header("User-agent")
        return _FakeHTTPResponse(200, b'{"id": "abc123"}')

    monkeypatch.setattr(auth_email_module.urllib.request, "urlopen", _fake_urlopen)
    ResendAuthEmailSender("re_secret", "from").send_verification_email(_message())
    user_agent = captured["user_agent"]
    assert isinstance(user_agent, str) and user_agent  # explicitly set, non-empty
    assert "python-urllib" not in user_agent.lower()  # never the Cloudflare-blocked default


@pytest.mark.parametrize(
    "status,category",
    [
        (401, AuthEmailErrorCategory.PROVIDER_AUTHENTICATION_ERROR),
        (403, AuthEmailErrorCategory.PROVIDER_AUTHENTICATION_ERROR),
        (429, AuthEmailErrorCategory.PROVIDER_RATE_LIMITED),
        (422, AuthEmailErrorCategory.PROVIDER_INVALID_REQUEST),
        (400, AuthEmailErrorCategory.PROVIDER_INVALID_REQUEST),
        (500, AuthEmailErrorCategory.PROVIDER_UNAVAILABLE),
        (503, AuthEmailErrorCategory.PROVIDER_UNAVAILABLE),
    ],
)
def test_resend_adapter_maps_http_errors(monkeypatch, status, category) -> None:
    def _raise(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError("https://api.resend.com/emails", status, "err", {}, None)

    monkeypatch.setattr(auth_email_module.urllib.request, "urlopen", _raise)
    with pytest.raises(AuthEmailError) as excinfo:
        ResendAuthEmailSender("re_secret", "from").send_verification_email(_message())
    assert excinfo.value.category is category
    # Error text never carries the key.
    assert "re_secret" not in str(excinfo.value)


def test_resend_adapter_maps_network_failure(monkeypatch) -> None:
    def _raise(request, timeout):  # noqa: ANN001
        raise urllib.error.URLError("connection refused to secret-host")

    monkeypatch.setattr(auth_email_module.urllib.request, "urlopen", _raise)
    with pytest.raises(AuthEmailError) as excinfo:
        ResendAuthEmailSender("re_secret", "from").send_verification_email(_message())
    assert excinfo.value.category is AuthEmailErrorCategory.PROVIDER_UNAVAILABLE
    assert "secret-host" not in str(excinfo.value)
    assert "re_secret" not in str(excinfo.value)


def test_resend_adapter_maps_malformed_success(monkeypatch) -> None:
    def _ok_but_garbage(request, timeout):  # noqa: ANN001
        return _FakeHTTPResponse(200, b"not-json")

    monkeypatch.setattr(auth_email_module.urllib.request, "urlopen", _ok_but_garbage)
    with pytest.raises(AuthEmailError) as excinfo:
        ResendAuthEmailSender("re_secret", "from").send_verification_email(_message())
    assert excinfo.value.category is AuthEmailErrorCategory.PROVIDER_INVALID_RESPONSE
