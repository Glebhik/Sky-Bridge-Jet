"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import type { Airport, CustomerTripRequest } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  airportLabel,
  formatDateTime,
  tripHandle,
  tripStatusTone,
} from "@/lib/portal/trip-requests";
import { canCancelTripRequest } from "@/lib/portal/trip-management";
import { TripCancelPanel } from "@/components/portal/TripCancelPanel";
import { OffersSection } from "@/components/portal/OffersSection";
import {
  Alert,
  Badge,
  Card,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";

interface TripRequestDetail {
  readonly trip: CustomerTripRequest;
  readonly airports: Readonly<Record<string, Airport>>;
}

/**
 * Load one trip request plus best-effort labels for the airports its legs reference. The
 * public `/airports/{id}` lookups are resolved with `allSettled` so a missing/unavailable
 * airport degrades to the leg's timezone rather than failing the whole page; only the
 * trip-request read itself can surface an error state.
 */
async function loadTripRequestDetail(
  id: string,
  organizationId: string | undefined,
  signal: AbortSignal,
): Promise<TripRequestDetail> {
  const trip = await portalApi.getTripRequest(id, organizationId, signal);
  const airportIds = [
    ...new Set(
      trip.legs.flatMap((leg) => [
        leg.origin_airport_id,
        leg.destination_airport_id,
      ]),
    ),
  ];
  const resolved = await Promise.allSettled(
    airportIds.map((airportId) => portalApi.getAirport(airportId, signal)),
  );
  const airports: Record<string, Airport> = {};
  for (const outcome of resolved) {
    if (outcome.status === "fulfilled")
      airports[outcome.value.id] = outcome.value;
  }
  return { trip, airports };
}

export default function PortalTripRequestDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { activeOrganizationId, hasCustomerContext } = useActiveOrganization();

  // A cancel replaces the displayed request with the real CANCELLED response (never optimistic);
  // a refresh (after a 409) clears that overlay and re-reads the request from the backend.
  const [override, setOverride] = useState<CustomerTripRequest | null>(null);
  const [justCancelled, setJustCancelled] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const load = useCallback(
    (signal: AbortSignal) =>
      loadTripRequestDetail(id, activeOrganizationId ?? undefined, signal),
    [id, activeOrganizationId],
  );
  const state = useApiResource<TripRequestDetail>(
    load,
    `trip-request:${id}:${activeOrganizationId ?? "none"}:${refreshNonce}`,
  );

  const backLink = (
    <p className="detail-back">
      <Link className="sbj-link" href="/portal/trip-requests">
        ← Back to trip requests
      </Link>
    </p>
  );

  if (!hasCustomerContext) {
    return (
      <>
        <PageHeading title="Trip request" />
        <Alert tone="warning" title="No active customer account">
          This trip request appears once your sign-in is linked to a customer
          account.
        </Alert>
        {backLink}
      </>
    );
  }

  if (state.status === "loading") {
    return (
      <>
        <PageHeading title="Trip request" />
        <LoadingState label="Loading this trip request…" />
      </>
    );
  }

  if (state.status === "error") {
    const notFound = state.error.status === 404;
    return (
      <>
        <PageHeading title="Trip request" />
        <Alert
          tone={notFound ? "warning" : "error"}
          title={
            notFound
              ? "Trip request not found"
              : state.error.isForbidden
                ? "You don’t have access to this trip request"
                : "We couldn’t load this trip request"
          }
        >
          {notFound
            ? "This trip request doesn’t exist or isn’t linked to your account."
            : state.error.isForbidden
              ? "This trip request belongs to a different account."
              : "Please refresh to try again."}
        </Alert>
        {backLink}
      </>
    );
  }

  const { airports } = state.data;
  // The overlay (a real CANCELLED response) wins over the loaded trip until a refresh clears it.
  const trip = override ?? state.data.trip;
  const orderedLegs = [...trip.legs].sort((a, b) => a.sequence - b.sequence);
  const req = trip.requirements;
  const notes: readonly { label: string; value: string }[] = [
    { label: "Baggage", value: req.baggage_notes ?? "" },
    { label: "Catering", value: req.catering_notes ?? "" },
    { label: "Special assistance", value: req.special_assistance_notes ?? "" },
    { label: "Notes", value: req.customer_notes ?? "" },
  ].filter((note) => note.value.length > 0);

  return (
    <>
      <PageHeading
        title={tripHandle(trip.id)}
        description="Your private-flight request."
      />

      <Card
        className={
          trip.status === "CANCELLED"
            ? "status-block status-block--cancelled"
            : "status-block"
        }
      >
        <div className="resource-list__row">
          <h2 className="card__title">Status</h2>
          <Badge tone={tripStatusTone(trip.status)}>{trip.status}</Badge>
        </div>
        <dl className="detail-list">
          <div>
            <dt>Requested</dt>
            <dd>{formatDateTime(trip.created_at)}</dd>
          </div>
          <div>
            <dt>Passengers</dt>
            <dd>{trip.passengers.length}</dd>
          </div>
        </dl>
        {justCancelled ? (
          <Alert tone="success" title="Request cancelled">
            Your trip request has been cancelled.
          </Alert>
        ) : null}
        {canCancelTripRequest(trip.status) ? (
          <div className="detail-actions">
            <TripCancelPanel
              trip={trip}
              organizationId={activeOrganizationId ?? undefined}
              onCancelled={(updated) => {
                setOverride(updated);
                setJustCancelled(true);
              }}
              onRefreshNeeded={() => {
                setOverride(null);
                setJustCancelled(false);
                setRefreshNonce((nonce) => nonce + 1);
              }}
            />
          </div>
        ) : null}
      </Card>

      <Card className="itinerary-card">
        <h2 className="card__title">Itinerary</h2>
        <ol className="itinerary">
          {orderedLegs.map((leg) => (
            <li key={leg.id} className="itinerary__leg">
              <span className="itinerary__route">
                <span className="itinerary__point">
                  {airportLabel(
                    airports[leg.origin_airport_id],
                    leg.origin_timezone,
                  )}
                </span>
                <span className="itinerary__arrow" aria-hidden="true">
                  →
                </span>
                <span className="itinerary__point">
                  {airportLabel(
                    airports[leg.destination_airport_id],
                    leg.destination_timezone,
                  )}
                </span>
              </span>
              <span className="itinerary__meta">
                Departs {formatDateTime(leg.departure_at)} ·{" "}
                {leg.passenger_count}{" "}
                {leg.passenger_count === 1 ? "passenger" : "passengers"}
              </span>
            </li>
          ))}
        </ol>
      </Card>

      <OffersSection
        tripRequestId={trip.id}
        tripStatus={trip.status}
        organizationId={activeOrganizationId ?? undefined}
      />

      {trip.passengers.length > 0 ? (
        <Card>
          <h2 className="card__title">Passengers</h2>
          <ul className="passenger-list">
            {trip.passengers.map((passenger) => (
              <li key={passenger.id}>
                {passenger.first_name} {passenger.last_name}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {notes.length > 0 || req.ground_transport_requested || req.pet_present ? (
        <Card>
          <h2 className="card__title">Requirements</h2>
          <dl className="detail-list">
            {notes.map((note) => (
              <div key={note.label}>
                <dt>{note.label}</dt>
                <dd>{note.value}</dd>
              </div>
            ))}
            {req.ground_transport_requested ? (
              <div>
                <dt>Ground transport</dt>
                <dd>Requested</dd>
              </div>
            ) : null}
            {req.pet_present ? (
              <div>
                <dt>Pet</dt>
                <dd>Travelling</dd>
              </div>
            ) : null}
          </dl>
        </Card>
      ) : null}

      {backLink}
    </>
  );
}
