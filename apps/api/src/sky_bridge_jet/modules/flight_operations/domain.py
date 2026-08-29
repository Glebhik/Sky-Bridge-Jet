from enum import StrEnum

from sky_bridge_jet.modules.core_aviation.domain import DomainError


class FlightOperationStatus(StrEnum):
    """Facts the D0 aggregate can authoritatively assert."""

    HANDOFF_CREATED = "HANDOFF_CREATED"


class FlightOperationError(DomainError):
    code = "flight_operation_error"


class FlightOperationEligibilityError(FlightOperationError):
    code = "flight_operation_not_allowed"
