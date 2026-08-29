from datetime import datetime
from enum import StrEnum

from sky_bridge_jet.modules.core_aviation.domain import DomainError


class NotificationDeliveryState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class MarketplaceNotificationEvent(StrEnum):
    """Closed server-owned catalog for Phase 9.8.C critical marketplace mail."""

    OFFER_AVAILABLE = "OFFER_AVAILABLE"
    BOOKING_PENDING_OPERATOR_CONFIRMATION = "BOOKING_PENDING_OPERATOR_CONFIRMATION"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    BOOKING_REJECTED = "BOOKING_REJECTED"


class NotificationFailureCode(StrEnum):
    TRANSIENT_PROVIDER = "TRANSIENT_PROVIDER"
    RECIPIENT_INELIGIBLE = "RECIPIENT_INELIGIBLE"
    INVALID_RECIPIENT = "INVALID_RECIPIENT"
    TEMPLATE_ERROR = "TEMPLATE_ERROR"
    UNKNOWN_DELIVERY_RESULT = "UNKNOWN_DELIVERY_RESULT"
    EVENT_NO_LONGER_APPLICABLE = "EVENT_NO_LONGER_APPLICABLE"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_SYSTEMIC_AUTH = "PROVIDER_SYSTEMIC_AUTH"
    PROVIDER_SYSTEMIC_POLICY = "PROVIDER_SYSTEMIC_POLICY"


class ProviderDeliveryState(StrEnum):
    """Provider facts; independent from outbox work ownership/state."""

    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    DELIVERY_DELAYED = "DELIVERY_DELAYED"
    BOUNCED = "BOUNCED"
    COMPLAINED = "COMPLAINED"
    SUPPRESSED = "SUPPRESSED"
    FAILED = "FAILED"


PROVIDER_EVENT_STATES = {
    "email.sent": ProviderDeliveryState.ACCEPTED,
    "email.delivered": ProviderDeliveryState.DELIVERED,
    "email.delivery_delayed": ProviderDeliveryState.DELIVERY_DELAYED,
    "email.bounced": ProviderDeliveryState.BOUNCED,
    "email.complained": ProviderDeliveryState.COMPLAINED,
    "email.suppressed": ProviderDeliveryState.SUPPRESSED,
    "email.failed": ProviderDeliveryState.FAILED,
}
PROVIDER_DELIVERY_PRECEDENCE = {
    None: 0,
    ProviderDeliveryState.ACCEPTED: 1,
    ProviderDeliveryState.DELIVERY_DELAYED: 2,
    ProviderDeliveryState.DELIVERED: 3,
    ProviderDeliveryState.FAILED: 4,
    ProviderDeliveryState.BOUNCED: 5,
    ProviderDeliveryState.SUPPRESSED: 6,
    ProviderDeliveryState.COMPLAINED: 7,
}


def provider_delivery_should_advance(
    *,
    current_state: str | None,
    current_occurred_at: datetime | None,
    candidate_state: ProviderDeliveryState,
    candidate_occurred_at: datetime,
) -> bool:
    """Order provider facts by provider time, then severity for equal instants.

    The complete signed event remains in the minimal ledger. The outbox projection
    intentionally represents the latest provider instant; an older high-risk event
    cannot falsify that timestamp, while a later complaint/bounce still escalates.
    """
    if current_occurred_at is None:
        return True
    if candidate_occurred_at != current_occurred_at:
        return candidate_occurred_at > current_occurred_at
    normalized_current = ProviderDeliveryState(current_state) if current_state is not None else None
    return PROVIDER_DELIVERY_PRECEDENCE[candidate_state] > PROVIDER_DELIVERY_PRECEDENCE.get(
        normalized_current, 0
    )


class RecipientFanoutError(DomainError):
    """A canonical recipient set exceeded the deliberately bounded policy."""

    code = "notification_recipient_fanout_exceeded"


class NotificationClaimConflictError(DomainError):
    """The supplied claim token no longer owns the notification."""

    code = "notification_claim_conflict"


class NotificationDedupeConflictError(DomainError):
    """A dedupe identity was reused for incompatible trusted notification facts."""

    code = "notification_dedupe_conflict"
