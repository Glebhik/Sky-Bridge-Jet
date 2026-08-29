from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.iam.domain import OrganizationType
from sky_bridge_jet.modules.iam.models import Organization
from sky_bridge_jet.modules.pilot_governance.domain import (
    PilotAccessDeniedError,
    PilotGovernanceConflictError,
    PilotGovernanceNotFoundError,
    PilotMode,
    PilotParticipantStatus,
    PilotParticipantType,
    PilotReason,
)
from sky_bridge_jet.modules.pilot_governance.models import (
    PILOT_GOVERNANCE_SINGLETON_ID,
    PilotGovernanceAudit,
    PilotGovernanceState,
    PilotParticipant,
)


def _now() -> datetime:
    return datetime.now(UTC)


class PilotAccessService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def state(self) -> PilotGovernanceState:
        state = self.session.get(PilotGovernanceState, PILOT_GOVERNANCE_SINGLETON_ID)
        if state is None:
            # Pure unit schemas use in-memory SQLite and do not run Alembic. Preserve the
            # migration's INTERNAL_ONLY default there; every supported PostgreSQL runtime
            # still fails closed if its mandatory singleton is absent.
            bind = self.session.get_bind()
            if bind.dialect.name == "sqlite":
                return PilotGovernanceState(
                    id=PILOT_GOVERNANCE_SINGLETON_ID,
                    mode=PilotMode.INTERNAL_ONLY,
                    payment_initiation_enabled=False,
                    version=1,
                )
            raise PilotAccessDeniedError("Pilot governance is unavailable")
        return state

    def _require(self, organization_id: UUID, expected: PilotParticipantType) -> None:
        state = self.state()
        if state.mode == PilotMode.INTERNAL_ONLY:
            return
        if state.mode == PilotMode.PAUSED:
            raise PilotAccessDeniedError("New controlled pilot journeys are paused")
        participant = self.session.scalar(
            select(PilotParticipant).where(PilotParticipant.organization_id == organization_id)
        )
        if (
            participant is None
            or participant.participant_type != expected
            or participant.status != PilotParticipantStatus.ACTIVE
        ):
            raise PilotAccessDeniedError(
                "This organization is not currently enabled for the controlled pilot"
            )

    def require_customer(self, customer_id: UUID | None) -> None:
        if self.state().mode == PilotMode.INTERNAL_ONLY:
            return
        if customer_id is None:
            raise PilotAccessDeniedError("Customer pilot organization is unavailable")
        org_id = self.session.scalar(
            select(Organization.id).where(Organization.customer_id == customer_id)
        )
        if org_id is None:
            raise PilotAccessDeniedError("Customer pilot organization is unavailable")
        self._require(org_id, PilotParticipantType.CUSTOMER)

    def require_operator(self, operator_id: UUID | None) -> None:
        if self.state().mode == PilotMode.INTERNAL_ONLY:
            return
        if operator_id is None:
            raise PilotAccessDeniedError("Operator pilot organization is unavailable")
        org_id = self.session.scalar(
            select(Organization.id).where(Organization.operator_id == operator_id)
        )
        if org_id is None:
            raise PilotAccessDeniedError("Operator pilot organization is unavailable")
        self._require(org_id, PilotParticipantType.OPERATOR)

    def require_payment_initiation(self, customer_id: UUID) -> None:
        self.require_customer(customer_id)
        state = self.state()
        if state.mode != PilotMode.INTERNAL_ONLY and not state.payment_initiation_enabled:
            raise PilotAccessDeniedError("Payment initiation is paused for the controlled pilot")


class PilotGovernanceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def state(self) -> PilotGovernanceState:
        state = self.session.get(
            PilotGovernanceState, PILOT_GOVERNANCE_SINGLETON_ID, with_for_update=False
        )
        if state is None:
            raise PilotGovernanceNotFoundError("Pilot governance state was not found")
        return state

    def update_state(
        self,
        *,
        actor: UUID,
        mode: PilotMode,
        payment_enabled: bool,
        expected_version: int,
        reason: PilotReason,
    ) -> PilotGovernanceState:
        with self.session.begin():
            state = self.session.get(
                PilotGovernanceState, PILOT_GOVERNANCE_SINGLETON_ID, with_for_update=True
            )
            if state is None:
                raise PilotGovernanceNotFoundError("Pilot governance state was not found")
            if state.version != expected_version:
                raise PilotGovernanceConflictError("Pilot governance state changed")
            previous = f"{state.mode.value}:{int(state.payment_initiation_enabled)}"
            target = f"{mode.value}:{int(payment_enabled)}"
            if previous == target:
                return state
            state.mode = mode
            state.payment_initiation_enabled = payment_enabled
            state.version += 1
            state.updated_at = _now()
            self.session.add(
                PilotGovernanceAudit(
                    actor_user_id=actor,
                    resource_type="GLOBAL",
                    action="UPDATE",
                    previous_state=previous,
                    new_state=target,
                    reason=reason,
                )
            )
        return state

    def create_participant(
        self, *, actor: UUID, organization_id: UUID, reason: PilotReason
    ) -> PilotParticipant:
        with self.session.begin():
            org = self.session.get(Organization, organization_id, with_for_update=True)
            if org is None or org.organization_type is OrganizationType.PLATFORM:
                raise PilotGovernanceConflictError("Organization is not a pilot participant")
            existing = self.session.scalar(
                select(PilotParticipant).where(PilotParticipant.organization_id == organization_id)
            )
            if existing is not None:
                return existing
            kind = (
                PilotParticipantType.CUSTOMER
                if org.organization_type is OrganizationType.CUSTOMER
                else PilotParticipantType.OPERATOR
            )
            participant = PilotParticipant(
                organization_id=organization_id,
                participant_type=kind,
                status=PilotParticipantStatus.INVITED,
            )
            self.session.add(participant)
            self.session.flush()
            self.session.add(
                PilotGovernanceAudit(
                    actor_user_id=actor,
                    participant_id=participant.id,
                    resource_type="PARTICIPANT",
                    action="INVITE",
                    previous_state="NONE",
                    new_state=PilotParticipantStatus.INVITED.value,
                    reason=reason,
                )
            )
        return participant

    def mutate_participant(
        self,
        participant_id: UUID,
        *,
        actor: UUID,
        status: PilotParticipantStatus,
        expected_version: int,
        reason: PilotReason,
    ) -> PilotParticipant:
        with self.session.begin():
            participant = self.session.get(PilotParticipant, participant_id, with_for_update=True)
            if participant is None:
                raise PilotGovernanceNotFoundError("Pilot participant was not found")
            if participant.version != expected_version:
                raise PilotGovernanceConflictError("Pilot participant changed")
            if participant.status is PilotParticipantStatus.REVOKED:
                raise PilotGovernanceConflictError("Revoked pilot access cannot be reactivated")
            if status is PilotParticipantStatus.INVITED:
                raise PilotGovernanceConflictError("Pilot participant cannot return to invited")
            if participant.status is status:
                return participant
            previous = participant.status
            participant.status = status
            participant.version += 1
            participant.updated_at = _now()
            self.session.add(
                PilotGovernanceAudit(
                    actor_user_id=actor,
                    participant_id=participant.id,
                    resource_type="PARTICIPANT",
                    action=status.value,
                    previous_state=previous.value,
                    new_state=status.value,
                    reason=reason,
                )
            )
        return participant

    def get_participant(self, participant_id: UUID) -> tuple[PilotParticipant, str]:
        row = self.session.execute(
            select(PilotParticipant, Organization.display_name)
            .join(Organization, Organization.id == PilotParticipant.organization_id)
            .where(PilotParticipant.id == participant_id)
        ).one_or_none()
        if row is None:
            raise PilotGovernanceNotFoundError("Pilot participant was not found")
        return row[0], row[1]

    def list_participants(
        self,
        *,
        limit: int,
        offset: int,
        status: PilotParticipantStatus | None = None,
        kind: PilotParticipantType | None = None,
    ) -> list[tuple[PilotParticipant, str]]:
        stmt = select(PilotParticipant, Organization.display_name).join(
            Organization, Organization.id == PilotParticipant.organization_id
        )
        if status is not None:
            stmt = stmt.where(PilotParticipant.status == status)
        if kind is not None:
            stmt = stmt.where(PilotParticipant.participant_type == kind)
        rows = self.session.execute(
            stmt.order_by(PilotParticipant.created_at, PilotParticipant.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return [(row[0], row[1]) for row in rows]

    def list_audits(self, *, limit: int, offset: int) -> list[PilotGovernanceAudit]:
        return list(
            self.session.scalars(
                select(PilotGovernanceAudit)
                .order_by(PilotGovernanceAudit.created_at.desc(), PilotGovernanceAudit.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
