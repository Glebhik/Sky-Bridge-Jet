from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sky_bridge_jet.modules.pilot_governance.domain import (
    PilotMode,
    PilotParticipantStatus,
    PilotParticipantType,
    PilotReason,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PilotStateResponse(StrictModel):
    id: UUID
    mode: PilotMode
    payment_initiation_enabled: bool
    version: int
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PilotStateCommand(StrictModel):
    mode: PilotMode
    payment_initiation_enabled: bool
    expected_version: int = Field(ge=1)
    reason: PilotReason


class ParticipantCreate(StrictModel):
    organization_id: UUID
    reason: PilotReason = PilotReason.PILOT_INVITATION


class ParticipantCommand(StrictModel):
    status: PilotParticipantStatus
    expected_version: int = Field(ge=1)
    reason: PilotReason


class ParticipantResponse(StrictModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    participant_type: PilotParticipantType
    status: PilotParticipantStatus
    version: int
    created_at: datetime
    updated_at: datetime


class PilotAuditResponse(StrictModel):
    id: UUID
    actor_user_id: UUID
    participant_id: UUID | None
    resource_type: str
    action: str
    previous_state: str
    new_state: str
    reason: PilotReason
    created_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")
