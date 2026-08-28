from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.compliance.domain import (
    AircraftAuthorizationStatus,
    ComplianceEntityType,
    EvidenceStatus,
    EvidenceType,
    OperatorAdmissionStatus,
)
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.core_aviation.models import Aircraft, Operator


class PlatformAdmissionRecord(NamedTuple):
    admission: OperatorAdmission
    operator_legal_name: str
    operator_trading_name: str | None
    operator_country_code: str


class PlatformEvidenceRecord(NamedTuple):
    evidence: ComplianceEvidence
    operator_legal_name: str
    operator_trading_name: str | None
    aircraft_registration: str | None


class PlatformAuthorizationRecord(NamedTuple):
    authorization: OperatorAircraftAuthorization
    operator_legal_name: str
    operator_trading_name: str | None
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str


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

    def get(self, admission_id: UUID) -> OperatorAdmission | None:
        return self.session.get(OperatorAdmission, admission_id)

    def list_platform_review(
        self, *, status: OperatorAdmissionStatus | None, limit: int, offset: int
    ) -> Sequence[PlatformAdmissionRecord]:
        statement = select(
            OperatorAdmission, Operator.legal_name, Operator.trading_name, Operator.country_code
        ).join(Operator, Operator.id == OperatorAdmission.operator_id)
        if status is not None:
            statement = statement.where(OperatorAdmission.status == status)
        statement = (
            statement.order_by(
                OperatorAdmission.submitted_at.asc().nulls_last(),
                OperatorAdmission.created_at.asc(),
                OperatorAdmission.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [PlatformAdmissionRecord(*row) for row in self.session.execute(statement).all()]


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

    def list_platform_review(
        self, *, status: EvidenceStatus | None, limit: int, offset: int
    ) -> Sequence[PlatformEvidenceRecord]:
        statement = (
            select(
                ComplianceEvidence,
                Operator.legal_name,
                Operator.trading_name,
                Aircraft.registration,
            )
            .join(Operator, Operator.id == ComplianceEvidence.operator_id)
            .outerjoin(Aircraft, Aircraft.id == ComplianceEvidence.aircraft_id)
        )
        if status is not None:
            statement = statement.where(ComplianceEvidence.status == status)
        statement = (
            statement.order_by(
                ComplianceEvidence.submitted_at.asc().nulls_last(),
                ComplianceEvidence.created_at.asc(),
                ComplianceEvidence.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [PlatformEvidenceRecord(*row) for row in self.session.execute(statement).all()]

    def operator_level_eligibility_facts(
        self, operator_id: UUID, evidence_type: EvidenceType, *, now: datetime
    ) -> tuple[bool, bool]:
        """Return bounded current/expired facts without materializing evidence history."""
        scope = (
            ComplianceEvidence.operator_id == operator_id,
            ComplianceEvidence.evidence_type == evidence_type,
            ComplianceEvidence.aircraft_id.is_(None),
            ComplianceEvidence.status == EvidenceStatus.VERIFIED,
        )
        current = exists().where(
            *scope,
            or_(ComplianceEvidence.expiry_date.is_(None), now < ComplianceEvidence.expiry_date),
        )
        expired = exists().where(
            *scope,
            and_(
                ComplianceEvidence.expiry_date.is_not(None),
                now >= ComplianceEvidence.expiry_date,
            ),
        )
        row = self.session.execute(select(current, expired)).one()
        return bool(row[0]), bool(row[1])


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

    def list_for_aircraft_ids(
        self, operator_id: UUID, aircraft_ids: Sequence[UUID]
    ) -> Sequence[OperatorAircraftAuthorization]:
        if not aircraft_ids:
            return ()
        statement = select(OperatorAircraftAuthorization).where(
            OperatorAircraftAuthorization.operator_id == operator_id,
            OperatorAircraftAuthorization.aircraft_id.in_(aircraft_ids),
        )
        return self.session.scalars(statement).all()

    def get(self, authorization_id: UUID) -> OperatorAircraftAuthorization | None:
        return self.session.get(OperatorAircraftAuthorization, authorization_id)

    def list_platform_review(
        self, *, status: AircraftAuthorizationStatus | None, limit: int, offset: int
    ) -> Sequence[PlatformAuthorizationRecord]:
        statement = (
            select(
                OperatorAircraftAuthorization,
                Operator.legal_name,
                Operator.trading_name,
                Aircraft.registration,
                Aircraft.manufacturer,
                Aircraft.model,
            )
            .join(Operator, Operator.id == OperatorAircraftAuthorization.operator_id)
            .join(Aircraft, Aircraft.id == OperatorAircraftAuthorization.aircraft_id)
        )
        if status is not None:
            statement = statement.where(OperatorAircraftAuthorization.status == status)
        statement = (
            statement.order_by(
                OperatorAircraftAuthorization.submitted_at.asc().nulls_last(),
                OperatorAircraftAuthorization.created_at.asc(),
                OperatorAircraftAuthorization.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [PlatformAuthorizationRecord(*row) for row in self.session.execute(statement).all()]

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
        self, entity_type: ComplianceEntityType, entity_id: UUID, *, limit: int | None = None
    ) -> Sequence[ComplianceAuditEvent]:
        statement = (
            select(ComplianceAuditEvent)
            .where(
                ComplianceAuditEvent.entity_type == entity_type,
                ComplianceAuditEvent.entity_id == entity_id,
            )
            .order_by(ComplianceAuditEvent.created_at.asc(), ComplianceAuditEvent.id.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.session.scalars(statement).all()
