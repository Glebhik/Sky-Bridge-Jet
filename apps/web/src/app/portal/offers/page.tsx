"use client";

import Link from "next/link";
import { useCallback } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import type { CustomerTripRequest } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  formatDateTime,
  legSummary,
  tripHandle,
  tripStatusTone,
} from "@/lib/portal/trip-requests";

export function compareOffersLandingTrips(
  a: CustomerTripRequest,
  b: CustomerTripRequest,
): number {
  const byCreated = Date.parse(b.created_at) - Date.parse(a.created_at);
  return byCreated || b.id.localeCompare(a.id);
}

/**
 * Trip-centric offers landing. There is intentionally no customer-wide offers endpoint:
 * this page performs one `/me/trip-requests` read and navigates to trip-scoped comparison.
 */
export default function PortalOffersPage() {
  const { activeOrganizationId, hasCustomerContext } = useActiveOrganization();
  const load = useCallback(
    (signal: AbortSignal) =>
      portalApi.listTripRequests(activeOrganizationId ?? undefined, signal),
    [activeOrganizationId],
  );
  const state = useApiResource<readonly CustomerTripRequest[]>(
    load,
    `offers-landing:${activeOrganizationId ?? "none"}`,
  );

  return (
    <div className="offers-landing">
      <PageHeading
        title="Offers"
        description="Published offers are available within each trip request."
      />
      {!hasCustomerContext ? (
        <Alert tone="warning" title="No active customer account">
          Offers appear once your sign-in is linked to a customer account.
        </Alert>
      ) : state.status === "loading" ? (
        <LoadingState label="Loading your trip requests…" />
      ) : state.status === "error" ? (
        <Alert tone="error" title="We couldn’t load your trip requests">
          Please refresh to try again.
        </Alert>
      ) : state.data.length === 0 ? (
        <EmptyState
          title="You don’t have any trip requests yet."
          description="Create a trip request to begin your private-flight journey."
          action={
            <Link
              className="button button--primary"
              href="/portal/trip-requests/new"
            >
              New trip request
            </Link>
          }
        />
      ) : (
        <ul className="resource-list trip-list">
          {[...state.data].sort(compareOffersLandingTrips).map((trip) => (
            <li key={trip.id}>
              <Card
                as="article"
                className={`trip-card trip-card--${tripStatusTone(trip.status)}`}
              >
                <div className="resource-list__row">
                  <Link
                    className="resource-list__reference"
                    href={`/portal/trip-requests/${trip.id}`}
                  >
                    {tripHandle(trip.id)}
                  </Link>
                  <Badge tone={tripStatusTone(trip.status)}>
                    {trip.status}
                  </Badge>
                </div>
                <p className="resource-list__meta">
                  {legSummary(trip)} · requested{" "}
                  {formatDateTime(trip.created_at)}
                </p>
                <p className="resource-list__actions">
                  <Link
                    className="button button--secondary"
                    href={`/portal/trip-requests/${trip.id}`}
                  >
                    View offers
                  </Link>
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
