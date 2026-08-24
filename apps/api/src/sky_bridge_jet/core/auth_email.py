"""Provider-neutral transactional auth-email seam (Phase 9.2.B1).

Mirrors the Stripe gateway seam (``core/stripe_gateway.py``): a narrow ``Protocol`` the
IAM layer depends on, a deterministic fake for tests (no network, no credentials), and a
real Resend adapter that performs a single REST call with the Python standard library.

Raw provider objects and exceptions never cross this boundary; every failure is
normalized to :class:`AuthEmailError` with a stable :class:`AuthEmailErrorCategory`. The
API key, the ``Authorization`` header, the raw verification token, and the full
verification URL are never placed in an exception message and never logged here.

Scope: verification email only (Phase 9.2.B1). Password-reset delivery is intentionally
not implemented in this slice; a later slice can add a method to this same seam without
changing the IAM domain rules.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sky_bridge_jet.core.config import Settings

RESEND_EMAILS_ENDPOINT = "https://api.resend.com/emails"
_DEFAULT_TIMEOUT_SECONDS = 10.0
# `api.resend.com` is fronted by Cloudflare, which blocks the stdlib default
# ``User-Agent: Python-urllib/x.y`` with HTTP 403 "error code: 1010". We therefore send an
# explicit, identifying User-Agent so the request is not bot-blocked (curl works precisely
# because its default UA is not blocked). This header carries no secret.
_USER_AGENT = "SkyBridgeJet-AuthEmail/1.0"


class AuthEmailErrorCategory(StrEnum):
    """Stable, provider-neutral categories for auth-email delivery failures."""

    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_AUTHENTICATION_ERROR = "PROVIDER_AUTHENTICATION_ERROR"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_INVALID_REQUEST = "PROVIDER_INVALID_REQUEST"
    PROVIDER_INVALID_RESPONSE = "PROVIDER_INVALID_RESPONSE"
    PROVIDER_CONFIGURATION_ERROR = "PROVIDER_CONFIGURATION_ERROR"


class AuthEmailError(Exception):
    """Raised by an adapter for a delivery failure; never leaks key/token/URL/headers."""

    def __init__(
        self,
        category: AuthEmailErrorCategory,
        message: str = "An auth email could not be sent",
    ) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class VerificationEmail:
    """A fully rendered verification message, ready for any sender to transmit."""

    to: str
    subject: str
    text_body: str
    html_body: str


class AuthEmailSender(Protocol):
    """Provider-neutral surface the IAM layer depends on (never a raw SDK/HTTP client)."""

    def send_verification_email(self, message: VerificationEmail) -> None: ...


@dataclass
class FakeAuthEmailSender:
    """Deterministic in-memory sender for tests. Records every message; no network call.

    This is the normal automated-test boundary; no automated test calls the real Resend
    API. ``sent`` preserves send order so a test can assert recipient/subject/body/link.
    """

    sent: list[VerificationEmail] = field(default_factory=list)

    def send_verification_email(self, message: VerificationEmail) -> None:
        self.sent.append(message)


class ResendAuthEmailSender:
    """Real adapter: one JSON ``POST`` to the Resend REST API via stdlib ``urllib``.

    Synchronous and bounded by an explicit timeout, consistent with the app's sync
    request model (sync routes run in a threadpool). The API key and Authorization header
    are set server-side and never logged; provider exceptions are caught and re-raised as
    a bare :class:`AuthEmailError` (the original — which may carry the response body or
    headers — is deliberately not chained).
    """

    def __init__(
        self,
        api_key: str,
        sender: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._sender = sender
        self._timeout = timeout_seconds

    def send_verification_email(self, message: VerificationEmail) -> None:
        payload = json.dumps(
            {
                "from": self._sender,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text_body,
                "html": message.html_body,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            RESEND_EMAILS_ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Required: the stdlib default UA is Cloudflare-blocked (see _USER_AGENT).
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = int(response.status)
                body = response.read()
        except urllib.error.HTTPError as error:
            # Do NOT chain: the HTTPError can expose response headers/body.
            raise _error_for_status(int(error.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise AuthEmailError(
                AuthEmailErrorCategory.PROVIDER_UNAVAILABLE,
                "The email provider is temporarily unavailable",
            ) from None

        if status < 200 or status >= 300:
            raise _error_for_status(status)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise AuthEmailError(
                AuthEmailErrorCategory.PROVIDER_INVALID_RESPONSE,
                "The email provider returned an unexpected response",
            ) from None
        if not isinstance(parsed, dict) or not parsed.get("id"):
            raise AuthEmailError(
                AuthEmailErrorCategory.PROVIDER_INVALID_RESPONSE,
                "The email provider returned an unexpected response",
            )


def _error_for_status(status: int) -> AuthEmailError:
    """Map an HTTP status to a provider-neutral category. Message carries no secrets."""
    if status in (401, 403):
        return AuthEmailError(
            AuthEmailErrorCategory.PROVIDER_AUTHENTICATION_ERROR,
            "The email provider rejected the credentials",
        )
    if status == 429:
        return AuthEmailError(
            AuthEmailErrorCategory.PROVIDER_RATE_LIMITED,
            "The email provider is rate limiting requests",
        )
    if 400 <= status < 500:
        return AuthEmailError(
            AuthEmailErrorCategory.PROVIDER_INVALID_REQUEST,
            "The email provider rejected the request",
        )
    return AuthEmailError(
        AuthEmailErrorCategory.PROVIDER_UNAVAILABLE,
        "The email provider is temporarily unavailable",
    )


def build_auth_email_sender(settings: Settings) -> AuthEmailSender:
    """Construct the configured sender: fake when disabled, Resend when enabled.

    Fails closed — enabled without an API key raises a configuration error whose message
    never contains the key. (Settings validation already rejects this at construction;
    this is defensive redundancy at the injection seam.)
    """
    if not settings.auth_email_enabled:
        return FakeAuthEmailSender()
    if not settings.resend_api_key:
        raise AuthEmailError(
            AuthEmailErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            "Auth email is enabled but no provider API key is configured",
        )
    return ResendAuthEmailSender(settings.resend_api_key, settings.auth_email_from)
