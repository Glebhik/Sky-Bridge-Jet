"use client";

import Link from "next/link";
import { useCallback } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import type { CustomerTripRequest } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  legSummary,
  passengerCount,
  tripHandle,
  tripStatusTone,
} from "@/lib/portal/trip-requests";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";

/**
 * Trip requests list — a real, org-scoped read of the customer's own trip requests
 * (`/me/trip-requests`) with honest loading / empty / error / list states. It renders only
 * the customer-safe read-model fields (status, legs, passenger roster, dates) and links to a
 * read-only detail. There is no create/submit/cancel here — those are later 9.3 slices.
 */
export default function PortalTripRequestsPage() {
  const { activeOrganizationId, hasCustomerContext } = useActiveOrganization();
  const load = useCallback(
    (signal: AbortSignal) =>
      portalApi.listTripRequests(activeOrganizationId ?? undefined, signal),
    [activeOrganizationId],
  );
  const state = useApiResource<readonly CustomerTripRequest[]>(
    load,
    `trip-requests:${activeOrganizationId ?? "none"}`,
  );

  return (
    <>
      <PageHeading
        title="Trip requests"
        description="Private-flight requests linked to your customer account."
      />
      {hasCustomerContext ? (
        <p className="resource-list__actions">
          <Link
            className="button button--primary"
            href="/portal/trip-requests/new"
          >
            New trip request
          </Link>
        </p>
      ) : null}
      {!hasCustomerContext ? (
        <Alert tone="warning" title="No active customer account">
          Trip requests appear once your sign-in is linked to a customer
          account.
        </Alert>
      ) : state.status === "loading" ? (
        <LoadingState label="Loading your trip requests…" />
      ) : state.status === "error" ? (
        <Alert tone="error" title="We couldn’t load your trip requests">
          {state.error.isForbidden
            ? "You don’t have access to these trip requests."
            : "Please refresh to try again."}
        </Alert>
      ) : state.data.length === 0 ? (
        <EmptyState
          title="No trip requests yet"
          description="When you request a private flight, it will appear here."
        />
      ) : (
        <ul className="resource-list">
          {state.data.map((trip) => (
            <li key={trip.id}>
              <Card as="article">
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
                  {legSummary(trip)} · {passengerCount(trip)}{" "}
                  {passengerCount(trip) === 1 ? "passenger" : "passengers"}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
