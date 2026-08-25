"use client";

import { useCallback } from "react";

import { portalApi } from "@/lib/api/client";
import type { CustomerOffer } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  compareCustomerOffers,
  formatOfferMoney,
  offerAvailability,
  serviceItems,
} from "@/lib/portal/offers";
import { formatDateTime } from "@/lib/portal/trip-requests";
import { Alert, Badge, Card, LoadingState } from "@/components/ui/primitives";

interface Props {
  readonly tripRequestId: string;
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

function OfferCard({ offer }: { offer: CustomerOffer }) {
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
      </article>
    </li>
  );
}

export function OffersSection({ tripRequestId, organizationId }: Props) {
  const load = useCallback(
    (signal: AbortSignal) =>
      portalApi.listTripRequestOffers(tripRequestId, organizationId, signal),
    [tripRequestId, organizationId],
  );
  const state = useApiResource<readonly CustomerOffer[]>(
    load,
    `offers:${tripRequestId}:${organizationId ?? "none"}`,
  );
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
        <ul className="offer-grid">
          {[...state.data].sort(compareCustomerOffers).map((offer) => (
            <OfferCard key={offer.id} offer={offer} />
          ))}
        </ul>
      ) : null}
    </Card>
  );
}
