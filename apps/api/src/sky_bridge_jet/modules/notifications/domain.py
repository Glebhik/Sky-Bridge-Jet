from enum import StrEnum

from sky_bridge_jet.modules.core_aviation.domain import DomainError


class NotificationDeliveryState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class NotificationClaimConflictError(DomainError):
    """The supplied claim token no longer owns the notification."""

    code = "notification_claim_conflict"


class NotificationDedupeConflictError(DomainError):
    """A dedupe identity was reused for incompatible trusted notification facts."""

    code = "notification_dedupe_conflict"
