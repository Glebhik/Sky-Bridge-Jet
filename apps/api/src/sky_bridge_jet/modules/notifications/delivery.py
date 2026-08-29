from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.modules.notifications.domain import NotificationFailureCode

MAX_PROVIDER_RESPONSE_BYTES = 8192


@dataclass(frozen=True)
class MarketplaceEmail:
    """A fixed server-rendered message passed to the provider-neutral boundary."""

    recipient: str
    subject: str
    text_body: str
    idempotency_key: str = "test-notification"


@dataclass(frozen=True)
class DeliveryAcceptance:
    provider_message_id: str
    provider_request_id: str | None = None


class NotificationDeliveryError(Exception):
    """Safe normalized failure; never contains a raw provider response."""

    def __init__(
        self, code: NotificationFailureCode, *, retryable: bool, systemic: bool = False
    ) -> None:
        super().__init__("Marketplace notification delivery failed")
        self.code = code
        self.retryable = retryable
        self.systemic = systemic


class MarketplaceNotificationSender(Protocol):
    def send(self, message: MarketplaceEmail) -> DeliveryAcceptance: ...


class ReadableProviderResponse(Protocol):
    def read(self, limit: int = -1) -> bytes: ...


class FakeDeliveryMode(StrEnum):
    SUCCESS = "SUCCESS"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    ACCEPTED_UNKNOWN = "ACCEPTED_UNKNOWN"


@dataclass
class FakeMarketplaceNotificationSender:
    """Deterministic local evidence seam. It performs no external network access."""

    mode: FakeDeliveryMode = FakeDeliveryMode.SUCCESS
    attempts: list[MarketplaceEmail] = field(default_factory=list)
    accepted: list[MarketplaceEmail] = field(default_factory=list)

    def send(self, message: MarketplaceEmail) -> DeliveryAcceptance:
        self.attempts.append(message)
        if self.mode is FakeDeliveryMode.SUCCESS:
            self.accepted.append(message)
            return DeliveryAcceptance(provider_message_id=f"fake-{message.idempotency_key}")
        if self.mode is FakeDeliveryMode.TRANSIENT_FAILURE:
            raise NotificationDeliveryError(
                NotificationFailureCode.TRANSIENT_PROVIDER, retryable=True
            )
        if self.mode is FakeDeliveryMode.PERMANENT_FAILURE:
            raise NotificationDeliveryError(
                NotificationFailureCode.INVALID_RECIPIENT, retryable=False
            )
        self.accepted.append(message)
        raise NotificationDeliveryError(
            NotificationFailureCode.UNKNOWN_DELIVERY_RESULT, retryable=True
        )


class ResendMarketplaceNotificationSender:
    """One bounded HTTPS POST. Dispatcher—not the adapter—owns retries."""

    endpoint = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str,
        from_address: str,
        *,
        timeout_seconds: float,
        reply_to: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.from_address = from_address
        self.timeout_seconds = timeout_seconds
        self.reply_to = reply_to

    def send(self, message: MarketplaceEmail) -> DeliveryAcceptance:
        payload: dict[str, object] = {
            "from": self.from_address,
            "to": [message.recipient],
            "subject": message.subject,
            "text": message.text_body,
        }
        if self.reply_to:
            payload["reply_to"] = self.reply_to
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": message.idempotency_key,
                "User-Agent": "sky-bridge-jet-marketplace-notifications/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = self._read_bounded(response)
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as error:
            self._raise_http(error.code, self._read_bounded(error))
        except (urllib.error.URLError, TimeoutError):
            raise NotificationDeliveryError(
                NotificationFailureCode.UNKNOWN_DELIVERY_RESULT, retryable=True
            ) from None
        try:
            provider_message_id = json.loads(raw)["id"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise NotificationDeliveryError(
                NotificationFailureCode.UNKNOWN_DELIVERY_RESULT, retryable=True
            ) from None
        if (
            not isinstance(provider_message_id, str)
            or not provider_message_id
            or len(provider_message_id) > 255
        ):
            raise NotificationDeliveryError(
                NotificationFailureCode.UNKNOWN_DELIVERY_RESULT, retryable=True
            )
        return DeliveryAcceptance(
            provider_message_id=provider_message_id, provider_request_id=request_id
        )

    @staticmethod
    def _read_bounded(response: ReadableProviderResponse) -> bytes:
        raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
        if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
            raise NotificationDeliveryError(
                NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY,
                retryable=True,
                systemic=True,
            )
        return raw

    @staticmethod
    def _provider_error_name(raw: bytes) -> str | None:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        name = payload.get("name") or payload.get("code")
        return name if isinstance(name, str) else None

    @classmethod
    def _raise_http(cls, status: int, raw: bytes) -> None:
        provider_error = cls._provider_error_name(raw)
        if status in {401, 403}:
            raise NotificationDeliveryError(
                NotificationFailureCode.PROVIDER_SYSTEMIC_AUTH, retryable=True, systemic=True
            )
        if status == 429:
            raise NotificationDeliveryError(
                NotificationFailureCode.PROVIDER_RATE_LIMIT, retryable=True, systemic=True
            )
        if status >= 500:
            raise NotificationDeliveryError(
                NotificationFailureCode.TRANSIENT_PROVIDER, retryable=True, systemic=True
            )
        if status == 409:
            if provider_error == "concurrent_idempotent_requests":
                raise NotificationDeliveryError(
                    NotificationFailureCode.TRANSIENT_PROVIDER,
                    retryable=True,
                    systemic=True,
                )
            raise NotificationDeliveryError(
                NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY,
                retryable=True,
                systemic=True,
            )
        if status in {400, 422} and provider_error in {
            "invalid_recipient",
            "invalid_to_address",
        }:
            raise NotificationDeliveryError(
                NotificationFailureCode.INVALID_RECIPIENT, retryable=False
            )
        raise NotificationDeliveryError(
            NotificationFailureCode.PROVIDER_SYSTEMIC_POLICY, retryable=True, systemic=True
        )


def build_marketplace_notification_sender(settings: Settings) -> MarketplaceNotificationSender:
    if not settings.marketplace_email_enabled:
        raise ValueError("Marketplace email delivery is disabled")
    if settings.marketplace_email_provider == "fake":
        if settings.app_environment not in {"development", "test"}:
            raise ValueError("FAKE marketplace email is restricted to development/test")
        return FakeMarketplaceNotificationSender()
    if not settings.resend_api_key:
        raise ValueError("Marketplace email provider configuration is incomplete")
    return ResendMarketplaceNotificationSender(
        settings.resend_api_key,
        settings.marketplace_email_from,
        timeout_seconds=settings.marketplace_email_timeout_seconds,
        reply_to=settings.marketplace_email_reply_to,
    )
