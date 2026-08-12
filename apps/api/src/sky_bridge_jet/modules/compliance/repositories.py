from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.compliance.domain import ComplianceEntityType, EvidenceType
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)


class OperatorAdmissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, admission: OperatorAdmission) -> OperatorAdmission:
        self.session.add(admission)
        return admission

    def get_by_operator(self, operator_id: UUID) -> OperatorAdmission | None:
        return self.session.scalar(
            select(OperatorAdmission).where(OperatorAdmission.operator_id == operator_id)
        )

    def get_by_operator_for_update(self, operator_id: UUID) -> OperatorAdmission | None:
        return self.session.scalar(
            select(OperatorAdmission)
            .where(OperatorAdmission.operator_id == operator_id)
            .with_for_update()
        )


class ComplianceEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, evidence: ComplianceEvidence) -> ComplianceEvidence:
        self.session.add(evidence)
        return evidence

    def get(self, evidence_id: UUID) -> ComplianceEvidence | None:
        return self.session.get(ComplianceEvidence, evidence_id)

    def get_for_update(self, evidence_id: UUID) -> ComplianceEvidence | None:
        return self.session.get(ComplianceEvidence, evidence_id, with_for_update=True)

    def list_for_operator(self, operator_id: UUID) -> Sequence[ComplianceEvidence]:
        statement = (
            select(ComplianceEvidence)
            .where(ComplianceEvidence.operator_id == operator_id)
            .order_by(ComplianceEvidence.created_at.asc(), ComplianceEvidence.id.asc())
        )
        return self.session.scalars(statement).all()

    def list_operator_level_by_type(
        self, operator_id: UUID, evidence_type: EvidenceType
    ) -> Sequence[ComplianceEvidence]:
        """Operator-level (not aircraft-scoped) evidence of a given type."""
        statement = select(ComplianceEvidence).where(
            ComplianceEvidence.operator_id == operator_id,
            ComplianceEvidence.evidence_type == evidence_type,
            ComplianceEvidence.aircraft_id.is_(None),
        )
        return self.session.scalars(statement).all()


class OperatorAircraftAuthorizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, authorization: OperatorAircraftAuthorization) -> OperatorAircraftAuthorization:
        self.session.add(authorization)
        return authorization

    def get_by_pair(
        self, operator_id: UUID, aircraft_id: UUID
    ) -> OperatorAircraftAuthorization | None:
        return self.session.scalar(self._by_pair(operator_id, aircraft_id))

    def get_by_pair_for_update(
        self, operator_id: UUID, aircraft_id: UUID
    ) -> OperatorAircraftAuthorization | None:
        return self.session.scalar(self._by_pair(operator_id, aircraft_id).with_for_update())

    @staticmethod
    def _by_pair(
        operator_id: UUID, aircraft_id: UUID
    ) -> Select[tuple[OperatorAircraftAuthorization]]:
        return select(OperatorAircraftAuthorization).where(
            OperatorAircraftAuthorization.operator_id == operator_id,
            OperatorAircraftAuthorization.aircraft_id == aircraft_id,
        )


class ComplianceAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: ComplianceAuditEvent) -> ComplianceAuditEvent:
        self.session.add(event)
        return event

    def list_for_entity(
        self, entity_type: ComplianceEntityType, entity_id: UUID
    ) -> Sequence[ComplianceAuditEvent]:
        statement = (
            select(ComplianceAuditEvent)
            .where(
                ComplianceAuditEvent.entity_type == entity_type,
                ComplianceAuditEvent.entity_id == entity_id,
            )
            .order_by(ComplianceAuditEvent.created_at.asc(), ComplianceAuditEvent.id.asc())
        )
        return self.session.scalars(statement).all()
