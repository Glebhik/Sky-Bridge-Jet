"use client";

import { useCallback, useRef, useState } from "react";

import { portalApi } from "@/lib/api/client";
import type { CustomerOffer } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  canSelectCustomerOffer,
  compareCustomerOffers,
  formatOfferMoney,
  offerAvailability,
  serviceItems,
} from "@/lib/portal/offers";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/portal/trip-requests";
import {
  Alert,
  Badge,
  Button,
  Card,
  LoadingState,
} from "@/components/ui/primitives";

interface Props {
  readonly tripRequestId: string;
  readonly tripStatus: string;
  readonly organizationId?: string;
}

function FactsList({ title, value }: { title: string; value: string | null }) {
  const items = serviceItems(value);
  if (items.length === 0) return null;
  return (
    <div className="offer-card__facts">
      <h4>{title}</h4>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function OfferCard({
  offer,
  canSelect,
  onSelect,
}: {
  offer: CustomerOffer;
  canSelect: boolean;
  onSelect: () => void;
}) {
  const availability = offerAvailability(offer.status);
  const tone =
    availability === "selected"
      ? "success"
      : availability === "available"
        ? "info"
        : "neutral";
  const status =
    availability === "selected"
      ? "Selected"
      : availability === "available"
        ? "Available"
        : availability === "expired"
          ? "Expired"
          : "Unavailable";
  return (
    <li className={`offer-card offer-card--${availability}`}>
      <article aria-label={`${offer.operator_legal_name} offer`}>
        <div className="offer-card__heading">
          <div>
            <p className="offer-card__price">
              {formatOfferMoney(offer.total_amount_minor, offer.currency)}
            </p>
            <p className="offer-card__currency">{offer.currency}</p>
          </div>
          <Badge tone={tone}>{status}</Badge>
        </div>
        <dl className="detail-list offer-card__details">
          <div>
            <dt>Operator</dt>
            <dd>{offer.operator_legal_name}</dd>
          </div>
          <div>
            <dt>Aircraft</dt>
            <dd>
              {offer.aircraft_manufacturer} {offer.aircraft_model} ·{" "}
              {offer.aircraft_category} · {offer.aircraft_registration}
            </dd>
          </div>
          <div>
            <dt>Tax included</dt>
            <dd>{formatOfferMoney(offer.tax_amount_minor, offer.currency)}</dd>
          </div>
          <div>
            <dt>Validity</dt>
            <dd>
              {offer.valid_until ? (
                <time dateTime={offer.valid_until}>
                  {availability === "expired" ? "Expired " : "Valid until "}
                  {formatDateTime(offer.valid_until)}
                </time>
              ) : (
                "Not specified"
              )}
            </dd>
          </div>
        </dl>
        <FactsList title="Included services" value={offer.included_services} />
        <FactsList title="Excluded services" value={offer.excluded_services} />
        {offer.cancellation_policy ? (
          <div className="offer-card__policy">
            <h4>Cancellation policy</h4>
            <p>{offer.cancellation_policy}</p>
          </div>
        ) : null}
        {canSelect ? (
          <div className="offer-card__actions">
            <Button variant="primary" onClick={onSelect}>
              Select offer
            </Button>
          </div>
        ) : null}
      </article>
    </li>
  );
}

export function OffersSection({
  tripRequestId,
  tripStatus,
  organizationId,
}: Props) {
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedResponse, setSelectedResponse] =
    useState<CustomerOffer | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [selectionError, setSelectionError] = useState<
    "conflict" | "other" | null
  >(null);
  const pendingRef = useRef(false);
  const load = useCallback(
    (signal: AbortSignal) =>
      portalApi.listTripRequestOffers(tripRequestId, organizationId, signal),
    [tripRequestId, organizationId],
  );
  const state = useApiResource<readonly CustomerOffer[]>(
    load,
    `offers:${tripRequestId}:${organizationId ?? "none"}:${refreshNonce}`,
  );
  const offers =
    state.status === "ready"
      ? state.data.map((offer) =>
          selectedResponse?.id === offer.id ? selectedResponse : offer,
        )
      : [];
  const confirmingOffer = offers.find((offer) => offer.id === confirmingId);

  const selectConfirmedOffer = async () => {
    if (!confirmingOffer || pendingRef.current) return;
    if (!canSelectCustomerOffer(tripStatus, confirmingOffer, offers)) return;
    pendingRef.current = true;
    setPending(true);
    setSelectionError(null);
    try {
      const selected = await portalApi.selectOffer(
        tripRequestId,
        confirmingOffer.id,
        organizationId,
      );
      setSelectedResponse(selected);
      setConfirmingId(null);
    } catch (error) {
      setSelectionError(
        error instanceof ApiError && error.status === 409
          ? "conflict"
          : "other",
      );
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  const refreshOffers = () => {
    setSelectionError(null);
    setConfirmingId(null);
    setSelectedResponse(null);
    setRefreshNonce((value) => value + 1);
  };
  return (
    <Card className="offers-section">
      <h2 className="card__title">Offers</h2>
      {state.status === "loading" ? (
        <LoadingState label="Loading published offers…" />
      ) : null}
      {state.status === "error" ? (
        <Alert tone="error" title="Offers couldn’t be loaded">
          Your trip request is still available above. Refresh to try loading
          offers again.
        </Alert>
      ) : null}
      {state.status === "ready" && state.data.length === 0 ? (
        <p className="empty-copy">
          No published offers are available for this trip request.
        </p>
      ) : null}
      {state.status === "ready" && state.data.length > 0 ? (
        <ul className="offer-grid" aria-busy={pending}>
          {[...offers].sort(compareCustomerOffers).map((offer) => (
            <OfferCard
              key={offer.id}
              offer={offer}
              canSelect={canSelectCustomerOffer(tripStatus, offer, offers)}
              onSelect={() => {
                setSelectionError(null);
                setConfirmingId(offer.id);
              }}
            />
          ))}
        </ul>
      ) : null}
      {confirmingOffer ? (
        <section
          className="offer-confirmation"
          aria-labelledby="offer-confirmation-title"
          aria-busy={pending}
        >
          <h3 id="offer-confirmation-title">Confirm offer selection</h3>
          <p>
            Selecting this offer does not create a booking and does not charge
            you. You cannot change the selected offer afterward.
          </p>
          <div className="offer-confirmation__actions">
            <Button
              variant="secondary"
              disabled={pending}
              onClick={() => setConfirmingId(null)}
            >
              Keep comparing
            </Button>
            <Button
              variant="primary"
              disabled={pending}
              onClick={() => void selectConfirmedOffer()}
            >
              {pending ? "Selecting…" : "Select this offer"}
            </Button>
          </div>
        </section>
      ) : null}
      {selectionError === "conflict" ? (
        <Alert tone="warning" title="Offer selection changed">
          This offer can no longer be selected, or another offer has already
          been selected.
          <Button variant="secondary" onClick={refreshOffers}>
            Refresh offers
          </Button>
        </Alert>
      ) : null}
      {selectionError === "other" ? (
        <Alert tone="error" title="Offer couldn’t be selected">
          No selection was made. Check your connection and try again.
        </Alert>
      ) : null}
    </Card>
  );
}
