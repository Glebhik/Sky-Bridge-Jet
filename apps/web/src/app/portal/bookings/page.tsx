"use client";

import { useCallback } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import type { CustomerBooking } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";

/**
 * Bookings placeholder — a real, org-scoped read of the customer's own bookings
 * (`/me/bookings`) with honest loading / empty / error / list states. It renders only the
 * customer-safe fields; there is no fabricated aircraft, pricing, or payment data, and no
 * booking-management workflow (that is a later phase).
 */
export default function PortalBookingsPage() {
  const { activeOrganizationId, hasCustomerContext } = useActiveOrganization();
  const load = useCallback(
    (signal: AbortSignal) =>
      portalApi.listBookings(activeOrganizationId ?? undefined, signal),
    [activeOrganizationId],
  );
  const state = useApiResource<readonly CustomerBooking[]>(
    load,
    `bookings:${activeOrganizationId ?? "none"}`,
  );

  return (
    <>
      <PageHeading
        title="Bookings"
        description="Bookings linked to your customer account."
      />
      {!hasCustomerContext ? (
        <Alert tone="warning" title="No active customer account">
          Bookings appear once your sign-in is linked to a customer account.
        </Alert>
      ) : state.status === "loading" ? (
        <LoadingState label="Loading your bookings…" />
      ) : state.status === "error" ? (
        <Alert tone="error" title="We couldn’t load your bookings">
          {state.error.isForbidden
            ? "You don’t have access to these bookings."
            : "Please refresh to try again."}
        </Alert>
      ) : state.data.length === 0 ? (
        <EmptyState
          title="No bookings yet"
          description="When you book a trip, it will appear here."
        />
      ) : (
        <ul className="resource-list trip-list">
          {state.data.map((booking) => (
            <li key={booking.id}>
              <Card as="article" className="trip-card">
                <div className="resource-list__row">
                  <span className="resource-list__reference">
                    {booking.reference}
                  </span>
                  <Badge tone="info">{booking.status}</Badge>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
