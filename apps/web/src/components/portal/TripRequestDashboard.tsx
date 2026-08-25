"use client";

import Link from "next/link";
import { useCallback } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import type { CustomerTripRequest } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  legSummary,
  tripHandle,
  tripStatusTone,
} from "@/lib/portal/trip-requests";
import {
  recentTripRequests,
  summarizeTripRequests,
} from "@/lib/portal/trip-management";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  LoadingState,
} from "@/components/ui/primitives";

/**
 * The dashboard trip-request summary (Phase 9.3.C). It computes factual counts and a small
 * "recent requests" list entirely client-side from the customer's real `/me/trip-requests`
 * data — no backend aggregation endpoint, no fabricated price/quote/operator/aircraft data.
 * It keys its read on the active organization, so a cancel elsewhere is reflected on refetch.
 */
export function TripRequestDashboard() {
  const { activeOrganizationId, hasCustomerContext } = useActiveOrganization();
  // Only read trip requests once there is a customer context (otherwise there is nothing to read).
  const load = useCallback(
    (signal: AbortSignal): Promise<readonly CustomerTripRequest[]> =>
      hasCustomerContext
        ? portalApi.listTripRequests(activeOrganizationId ?? undefined, signal)
        : Promise.resolve([]),
    [activeOrganizationId, hasCustomerContext],
  );
  const state = useApiResource<readonly CustomerTripRequest[]>(
    load,
    `dashboard-trips:${hasCustomerContext ? (activeOrganizationId ?? "none") : "no-context"}`,
  );

  const newRequestCta = (
    <Link className="button button--primary" href="/portal/trip-requests/new">
      New trip request
    </Link>
  );

  if (!hasCustomerContext) {
    return (
      <Card>
        <h2 className="card__title">Trip requests</h2>
        <Alert tone="warning" title="No active customer account">
          Your trip request summary appears once your sign-in is linked to a
          customer account.
        </Alert>
      </Card>
    );
  }

  if (state.status === "loading") {
    return (
      <Card>
        <h2 className="card__title">Trip requests</h2>
        <LoadingState label="Loading your trip request summary…" />
      </Card>
    );
  }

  if (state.status === "error") {
    return (
      <Card>
        <h2 className="card__title">Trip requests</h2>
        <Alert
          tone="error"
          title={
            state.error.isForbidden
              ? "You don’t have access to these trip requests"
              : "We couldn’t load your trip requests"
          }
        >
          {state.error.isForbidden
            ? "This account can’t view these trip requests."
            : "Please refresh to try again."}
        </Alert>
      </Card>
    );
  }

  const trips = state.data;
  if (trips.length === 0) {
    return (
      <Card>
        <h2 className="card__title">Trip requests</h2>
        <EmptyState
          title="No trip requests yet"
          description="When you request a private flight, it will appear here."
          action={newRequestCta}
        />
      </Card>
    );
  }

  const summary = summarizeTripRequests(trips);
  const recent = recentTripRequests(trips, 5);
  const stats: readonly { label: string; value: number }[] = [
    { label: "Total", value: summary.total },
    { label: "Active", value: summary.active },
    { label: "Submitted", value: summary.submitted },
    { label: "Cancelled", value: summary.cancelled },
  ];

  return (
    <Card className="dashboard-summary">
      <div className="resource-list__row dashboard-summary__head">
        <h2 className="card__title">Trip requests</h2>
        {newRequestCta}
      </div>
      <dl className="stat-grid">
        {stats.map((stat) => (
          <div className="stat" key={stat.label}>
            <dt className="stat__label">{stat.label}</dt>
            <dd className="stat__value">{stat.value}</dd>
          </div>
        ))}
      </dl>

      <h3 className="dashboard-subhead">Recent requests</h3>
      <ul className="resource-list resource-list--quiet">
        {recent.map((trip) => (
          <li key={trip.id} className="recent-request">
            <div className="resource-list__row">
              <Link
                className="resource-list__reference"
                href={`/portal/trip-requests/${trip.id}`}
              >
                {tripHandle(trip.id)}
              </Link>
              <Badge tone={tripStatusTone(trip.status)}>{trip.status}</Badge>
            </div>
            <p className="resource-list__meta">{legSummary(trip)}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
