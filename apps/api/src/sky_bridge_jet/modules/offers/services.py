from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.core_aviation.domain import (
    DomainValidationError,
    ResourceNotFoundError,
    TripRequestStatus,
)
from sky_bridge_jet.modules.core_aviation.models import TripRequest
from sky_bridge_jet.modules.core_aviation.repositories import (
    AircraftRepository,
    OperatorRepository,
    TripRequestRepository,
)
from sky_bridge_jet.modules.offers.domain import (
    InvalidOfferStateError,
    OfferNotSelectableError,
    OfferStatus,
    TripNotAcceptingOffersError,
    compute_platform_fee_minor,
    compute_total_minor,
    is_effectively_expired,
    validate_future_validity,
    validate_offer_transition,
    validate_price_consistency,
)
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.offers.repositories import OperatorOfferRepository
from sky_bridge_jet.modules.offers.schemas import OperatorOfferCreate, OperatorOfferUpdate


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


class OperatorOfferService:
    """Own operator-offer use cases within one explicit transaction per write.

    Authorization remains intentionally deferred for Phase 3. Each method is
    scoped to a single actor role — operators create/update/submit/withdraw
    offers; customers select them — so future authorization can wrap these
    boundaries without a redesign.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.offers = OperatorOfferRepository(session)
        self.trips = TripRequestRepository(session)
        self.operators = OperatorRepository(session)
        self.aircraft = AircraftRepository(session)

    # -- Operator actions ---------------------------------------------------

    def create(self, data: OperatorOfferCreate) -> OperatorOffer:
        with self.session.begin():
            trip = self.trips.get(data.trip_request_id)
            if trip is None:
                raise _not_found("Trip request")
            self._require_trip_accepting_offers(trip)

            operator = self.operators.get(data.operator_id)
            if operator is None:
                raise _not_found("Operator")
            aircraft = self.aircraft.get(data.aircraft_id)
            if aircraft is None:
                raise _not_found("Aircraft")
            if aircraft.operator_id != operator.id:
                raise DomainValidationError("Aircraft does not belong to the offering operator")

            platform_fee_minor = compute_platform_fee_minor(data.operator_amount_minor)
            total_amount_minor = compute_total_minor(
                operator_amount_minor=data.operator_amount_minor,
                platform_fee_minor=platform_fee_minor,
                tax_amount_minor=data.tax_amount_minor,
            )
            validate_price_consistency(
                operator_amount_minor=data.operator_amount_minor,
                platform_fee_minor=platform_fee_minor,
                tax_amount_minor=data.tax_amount_minor,
                total_amount_minor=total_amount_minor,
            )

            offer = self.offers.add(
                OperatorOffer(
                    trip_request_id=trip.id,
                    operator_id=operator.id,
                    aircraft_id=aircraft.id,
                    status=OfferStatus.DRAFT,
                    currency=data.currency,
                    operator_amount_minor=data.operator_amount_minor,
                    platform_fee_minor=platform_fee_minor,
                    tax_amount_minor=data.tax_amount_minor,
                    total_amount_minor=total_amount_minor,
                    valid_until=data.valid_until,
                    operator_legal_name=operator.legal_name,
                    aircraft_registration=aircraft.registration,
                    aircraft_manufacturer=aircraft.manufacturer,
                    aircraft_model=aircraft.model,
                    aircraft_category=aircraft.category.value,
                    operator_notes=data.operator_notes,
                    cancellation_policy=data.cancellation_policy,
                    included_services=data.included_services,
                    excluded_services=data.excluded_services,
                )
            )
            self.session.flush()
            return offer

    def update_draft(self, offer_id: UUID, data: OperatorOfferUpdate) -> OperatorOffer:
        with self.session.begin():
            offer = self.offers.get_for_update(offer_id)
            if offer is None:
                raise _not_found("Offer")
            if offer.status is not OfferStatus.DRAFT:
                raise InvalidOfferStateError("Only draft offers can be updated")

            fields = data.model_dump(exclude_unset=True)
            for column in (
                "currency",
                "operator_amount_minor",
                "tax_amount_minor",
                "valid_until",
                "operator_notes",
                "cancellation_policy",
                "included_services",
                "excluded_services",
            ):
                if column in fields:
                    setattr(offer, column, fields[column])

            offer.platform_fee_minor = compute_platform_fee_minor(offer.operator_amount_minor)
            offer.total_amount_minor = compute_total_minor(
                operator_amount_minor=offer.operator_amount_minor,
                platform_fee_minor=offer.platform_fee_minor,
                tax_amount_minor=offer.tax_amount_minor,
            )
            validate_price_consistency(
                operator_amount_minor=offer.operator_amount_minor,
                platform_fee_minor=offer.platform_fee_minor,
                tax_amount_minor=offer.tax_amount_minor,
                total_amount_minor=offer.total_amount_minor,
            )
            self.session.flush()
            return offer

    def submit(self, offer_id: UUID) -> OperatorOffer:
        with self.session.begin():
            offer = self.offers.get_for_update(offer_id)
            if offer is None:
                raise _not_found("Offer")
            validate_offer_transition(offer.status, OfferStatus.SUBMITTED)

            trip = self.trips.get(offer.trip_request_id)
            if trip is None:
                raise _not_found("Trip request")
            self._require_trip_accepting_offers(trip)

            if offer.valid_until is None:
                raise DomainValidationError("Offer validity is required before submission")
            validate_future_validity(offer.valid_until, now=_utc_now())

            offer.status = OfferStatus.SUBMITTED
            self.session.flush()
            return offer

    def withdraw(self, offer_id: UUID) -> OperatorOffer:
        with self.session.begin():
            offer = self.offers.get_for_update(offer_id)
            if offer is None:
                raise _not_found("Offer")
            validate_offer_transition(offer.status, OfferStatus.WITHDRAWN)
            offer.status = OfferStatus.WITHDRAWN
            self.session.flush()
            return offer

    # -- Customer action ----------------------------------------------------

    def select(self, trip_request_id: UUID, offer_id: UUID) -> OperatorOffer:
        with self.session.begin():
            # Lock the trip row first so concurrent selections for the same trip
            # serialize; the partial unique index is the ultimate backstop.
            trip = self.session.get(TripRequest, trip_request_id, with_for_update=True)
            if trip is None:
                raise _not_found("Trip request")
            if trip.status is not TripRequestStatus.SUBMITTED:
                raise TripNotAcceptingOffersError("Trip request is not accepting offer selections")

            offer = self.offers.get_for_update(offer_id)
            if offer is None or offer.trip_request_id != trip_request_id:
                raise _not_found("Offer")
            if offer.status is not OfferStatus.SUBMITTED:
                raise OfferNotSelectableError("Offer is not open for selection")
            if is_effectively_expired(offer.status, offer.valid_until, now=_utc_now()):
                raise OfferNotSelectableError("Offer has expired")
            if self.offers.get_selected_for_trip(trip_request_id) is not None:
                raise OfferNotSelectableError("Trip request already has a selected offer")

            offer.status = OfferStatus.SELECTED
            self.session.flush()
            return offer

    # -- Reads --------------------------------------------------------------

    def get(self, offer_id: UUID) -> OperatorOffer:
        offer = self.offers.get(offer_id)
        if offer is None:
            raise _not_found("Offer")
        return offer

    def list_for_trip(self, trip_request_id: UUID) -> list[OperatorOffer]:
        if self.trips.get(trip_request_id) is None:
            raise _not_found("Trip request")
        return list(self.offers.list_for_trip(trip_request_id))

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _require_trip_accepting_offers(trip: TripRequest) -> None:
        if trip.status is not TripRequestStatus.SUBMITTED:
            raise TripNotAcceptingOffersError(
                "Trip request is not accepting offers in its current state"
            )
