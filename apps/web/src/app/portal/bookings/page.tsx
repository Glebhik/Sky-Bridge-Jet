"use client";

import { useCallback } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import { bookingStatusLabel, bookingStatusTone } from "@/lib/portal/bookings";
import { formatOfferMoney } from "@/lib/portal/offers";
import { formatDateTime } from "@/lib/portal/trip-requests";
import { useBookingFreshness } from "@/lib/portal/use-booking-freshness";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";

function bookingVisualKind(status: string): string {
  if (status === "PENDING_OPERATOR_CONFIRMATION") return "pending";
  if (status === "CONFIRMED") return "confirmed";
  if (status === "REJECTED") return "rejected";
  if (status === "CANCELLED") return "cancelled";
  return "unknown";
}

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
  const { state, refresh } = useBookingFreshness(
    load,
    `bookings:${activeOrganizationId ?? "none"}`,
    hasCustomerContext,
  );

  return (
    <div className="bookings-landing">
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
        <section className="bookings-live" aria-busy={state.refreshing}>
          <div className="booking-freshness-controls">
            <Button
              variant="ghost"
              type="button"
              disabled={state.refreshing}
              onClick={() => void refresh()}
            >
              {state.refreshing ? "Refreshing…" : "Refresh status"}
            </Button>
            {state.warning ? (
              <p
                className="booking-freshness-warning"
                role="status"
                aria-live="polite"
              >
                {state.warning}
              </p>
            ) : null}
          </div>
          <ul className="resource-list booking-list">
            {state.data.map((booking) => {
              const kind = bookingVisualKind(booking.status);
              return (
                <li key={booking.id}>
                  <Card
                    as="article"
                    className={`booking-card booking-card--${kind}`}
                  >
                    <header className="booking-card__head">
                      <h2 className="booking-card__reference">
                        {booking.reference}
                      </h2>
                      <div className="booking-card__status">
                        <span
                          className={`booking-card__mark booking-card__mark--${kind}`}
                          aria-hidden="true"
                        />
                        <Badge tone={bookingStatusTone(booking.status)}>
                          {bookingStatusLabel(booking.status)}
                        </Badge>
                      </div>
                    </header>
                    <dl className="detail-list booking-card__details">
                      <div>
                        <dt>Operator</dt>
                        <dd className="booking-card__operator">
                          {booking.operator_legal_name}
                        </dd>
                      </div>
                      <div>
                        <dt>Aircraft</dt>
                        <dd className="booking-card__aircraft">
                          {booking.aircraft_manufacturer}{" "}
                          {booking.aircraft_model} · {booking.aircraft_category}{" "}
                          · {booking.aircraft_registration}
                        </dd>
                      </div>
                      <div>
                        <dt>Customer total</dt>
                        <dd className="booking-card__total">
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
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
