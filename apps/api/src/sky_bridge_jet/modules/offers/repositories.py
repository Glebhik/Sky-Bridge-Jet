from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.offers.domain import OfferStatus
from sky_bridge_jet.modules.offers.models import OperatorOffer


class OperatorOfferRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, offer: OperatorOffer) -> OperatorOffer:
        self.session.add(offer)
        return offer

    def get(self, offer_id: UUID) -> OperatorOffer | None:
        return self.session.get(OperatorOffer, offer_id)

    def get_for_update(self, offer_id: UUID) -> OperatorOffer | None:
        """Load an offer with a row lock so concurrent mutations serialize."""
        return self.session.get(OperatorOffer, offer_id, with_for_update=True)

    def list_for_trip(self, trip_request_id: UUID) -> Sequence[OperatorOffer]:
        """Return all offers for a trip in a stable, deterministic comparison order."""
        statement = (
            select(OperatorOffer)
            .where(OperatorOffer.trip_request_id == trip_request_id)
            .order_by(
                OperatorOffer.total_amount_minor.asc(),
                OperatorOffer.valid_until.desc().nulls_last(),
                OperatorOffer.created_at.asc(),
                OperatorOffer.id.asc(),
            )
        )
        return self.session.scalars(statement).all()

    def get_selected_for_trip(self, trip_request_id: UUID) -> OperatorOffer | None:
        """Return the currently selected offer for a trip, if any."""
        statement = select(OperatorOffer).where(
            OperatorOffer.trip_request_id == trip_request_id,
            OperatorOffer.status == OfferStatus.SELECTED,
        )
        return self.session.scalar(statement)
