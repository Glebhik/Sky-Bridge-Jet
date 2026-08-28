from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from sky_bridge_jet.modules.notifications.domain import NotificationFailureCode


@dataclass(frozen=True)
class MarketplaceEmail:
    """A fixed server-rendered message passed to the provider-neutral boundary."""

    recipient: str
    subject: str
    text_body: str


class NotificationDeliveryError(Exception):
    """Safe normalized failure; never contains a raw provider response."""

    def __init__(self, code: NotificationFailureCode, *, retryable: bool) -> None:
        super().__init__("Marketplace notification delivery failed")
        self.code = code
        self.retryable = retryable


class MarketplaceNotificationSender(Protocol):
    def send(self, message: MarketplaceEmail) -> None: ...


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

    def send(self, message: MarketplaceEmail) -> None:
        self.attempts.append(message)
        if self.mode is FakeDeliveryMode.SUCCESS:
            self.accepted.append(message)
            return
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
