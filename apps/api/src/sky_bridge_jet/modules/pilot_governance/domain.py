from enum import StrEnum

from sky_bridge_jet.modules.core_aviation.domain import DomainError


class PilotParticipantType(StrEnum):
    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"


class PilotParticipantStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PilotMode(StrEnum):
    INTERNAL_ONLY = "INTERNAL_ONLY"
    CONTROLLED_EXTERNAL = "CONTROLLED_EXTERNAL"
    PAUSED = "PAUSED"


class PilotReason(StrEnum):
    PILOT_INVITATION = "PILOT_INVITATION"
    OWNER_APPROVED = "OWNER_APPROVED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    COMPLIANCE_CONCERN = "COMPLIANCE_CONCERN"
    SECURITY_OR_PRIVACY_CONCERN = "SECURITY_OR_PRIVACY_CONCERN"
    PAYMENT_AMBIGUITY = "PAYMENT_AMBIGUITY"
    OPERATIONAL_PAUSE = "OPERATIONAL_PAUSE"
    ACCESS_NO_LONGER_REQUIRED = "ACCESS_NO_LONGER_REQUIRED"


class PilotGovernanceError(DomainError):
    code = "pilot_governance_error"


class PilotAccessDeniedError(PilotGovernanceError):
    code = "pilot_access_denied"


class PilotGovernanceConflictError(PilotGovernanceError):
    code = "pilot_governance_conflict"


class PilotGovernanceNotFoundError(PilotGovernanceError):
    code = "pilot_participant_not_found"
