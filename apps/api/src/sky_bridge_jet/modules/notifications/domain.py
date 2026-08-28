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


class RecipientFanoutError(DomainError):
    """A canonical recipient set exceeded the deliberately bounded policy."""

    code = "notification_recipient_fanout_exceeded"


class NotificationClaimConflictError(DomainError):
    """The supplied claim token no longer owns the notification."""

    code = "notification_claim_conflict"


class NotificationDedupeConflictError(DomainError):
    """A dedupe identity was reused for incompatible trusted notification facts."""

    code = "notification_dedupe_conflict"
