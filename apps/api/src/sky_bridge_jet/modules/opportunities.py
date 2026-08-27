"""Operator-safe, read-only marketplace opportunity projection."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from sky_bridge_jet.modules.compliance.evaluator import ComplianceEvaluator
from sky_bridge_jet.modules.core_aviation.domain import TripRequestStatus
from sky_bridge_jet.modules.core_aviation.models import TripLeg, TripRequest
from sky_bridge_jet.modules.core_aviation.schemas import (
    OperatorOpportunityLegResponse,
    OperatorOpportunityOwnOfferResponse,
    OperatorOpportunityResponse,
)
from sky_bridge_jet.modules.offers.domain import effective_offer_status
from sky_bridge_jet.modules.offers.models import OperatorOffer


class OperatorOpportunityService:
    """Build a bounded projection without loading customer or passenger relationships."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_operator(
        self, operator_id: UUID, *, limit: int, offset: int
    ) -> list[OperatorOpportunityResponse]:
        # Offer creation already fails closed on marketplace compliance. Discovery uses
        # the operator-level portion of the same evaluator; aircraft-specific eligibility
        # remains authoritative when an aircraft is chosen for an offer.
        if not ComplianceEvaluator(self.session).evaluate_operator(operator_id).eligible:
            return []

        trips = list(
            self.session.scalars(
                select(TripRequest)
                .where(TripRequest.status == TripRequestStatus.SUBMITTED)
                .options(
                    selectinload(TripRequest.legs).options(
                        joinedload(TripLeg.origin_airport),
                        joinedload(TripLeg.destination_airport),
                    )
                )
                .order_by(TripRequest.created_at.asc(), TripRequest.id.asc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        if not trips:
            return []

        trip_ids = [trip.id for trip in trips]
        offers = self.session.scalars(
            select(OperatorOffer)
            .where(
                OperatorOffer.operator_id == operator_id,
                OperatorOffer.trip_request_id.in_(trip_ids),
            )
            .order_by(
                OperatorOffer.trip_request_id.asc(),
                OperatorOffer.created_at.asc(),
                OperatorOffer.id.asc(),
            )
        ).all()
        own_by_trip: dict[UUID, list[OperatorOpportunityOwnOfferResponse]] = defaultdict(list)
        now = datetime.now(UTC)
        for offer in offers:
            own_by_trip[offer.trip_request_id].append(
                OperatorOpportunityOwnOfferResponse(
                    offer_id=offer.id,
                    status=effective_offer_status(offer.status, offer.valid_until, now=now),
                )
            )

        return [
            OperatorOpportunityResponse(
                trip_request_id=trip.id,
                status=trip.status,
                legs=[
                    OperatorOpportunityLegResponse(
                        sequence=leg.sequence,
                        origin_airport_code=leg.origin_airport.icao_code,
                        destination_airport_code=leg.destination_airport.icao_code,
                        departure_at=leg.departure_at,
                        passenger_count=leg.passenger_count,
                    )
                    for leg in trip.legs
                ],
                own_offers=own_by_trip[trip.id],
                created_at=trip.created_at,
            )
            for trip in trips
        ]
