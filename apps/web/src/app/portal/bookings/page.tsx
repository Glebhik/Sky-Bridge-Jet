"use client";

import { useCallback } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import type { CustomerBooking } from "@/lib/api/types";
import { bookingStatusLabel, bookingStatusTone } from "@/lib/portal/bookings";
import { formatOfferMoney } from "@/lib/portal/offers";
import { formatDateTime } from "@/lib/portal/trip-requests";
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
 * Booking mutation other than customer creation remains outside this page.
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
                  <Badge tone={bookingStatusTone(booking.status)}>
                    {bookingStatusLabel(booking.status)}
                  </Badge>
                </div>
                <dl className="detail-list">
                  <div>
                    <dt>Operator</dt>
                    <dd>{booking.operator_legal_name}</dd>
                  </div>
                  <div>
                    <dt>Aircraft</dt>
                    <dd>
                      {booking.aircraft_manufacturer} {booking.aircraft_model} ·{" "}
                      {booking.aircraft_category} ·{" "}
                      {booking.aircraft_registration}
                    </dd>
                  </div>
                  <div>
                    <dt>Customer total</dt>
                    <dd>
                      {formatOfferMoney(
                        booking.total_amount_minor,
                        booking.currency,
                      )}{" "}
                      {booking.currency}
                    </dd>
                  </div>
                  <div>
                    <dt>Requested</dt>
                    <dd>
                      <time dateTime={booking.created_at}>
                        {formatDateTime(booking.created_at)}
                      </time>
                    </dd>
                  </div>
                  {booking.confirmed_at ? (
                    <div>
                      <dt>Operator confirmed</dt>
                      <dd>
                        <time dateTime={booking.confirmed_at}>
                          {formatDateTime(booking.confirmed_at)}
                        </time>
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
