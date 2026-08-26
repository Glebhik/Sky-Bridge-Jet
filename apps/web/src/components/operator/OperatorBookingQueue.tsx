"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Alert,
  Button,
  Card,
  Container,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { BookingRejectionReason, OperatorBooking } from "@/lib/api/types";

const REASONS: readonly BookingRejectionReason[] = [
  "AIRCRAFT_UNAVAILABLE",
  "SCHEDULE_CONFLICT",
  "OPERATIONAL_RESTRICTION",
  "COMMERCIAL_WITHDRAWAL",
  "OTHER",
];

function money(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(
    value / 100,
  );
}

export function OperatorBookingQueue({
  organizations,
}: {
  readonly organizations: readonly {
    readonly id: string;
    readonly role: string;
    readonly canDecide: boolean;
  }[];
}) {
  const [organizationId, setOrganizationId] = useState(
    organizations.length === 1 ? organizations[0].id : "",
  );
  const [items, setItems] = useState<readonly OperatorBooking[] | null>(null);
  const [error, setError] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState<BookingRejectionReason>(
    "AIRCRAFT_UNAVAILABLE",
  );
  const guard = useRef(false);
  const activeOrganizationId = useRef(organizationId);

  const activeOrganization = organizations.find(
    (organization) => organization.id === organizationId,
  );

  const load = useCallback(async () => {
    if (!organizationId) return;
    try {
      const bookings = await portalApi.listOperatorBookings(organizationId);
      if (activeOrganizationId.current === organizationId) setItems(bookings);
    } catch {
      if (activeOrganizationId.current === organizationId) {
        setError(true);
        setItems([]);
      }
    }
  }, [organizationId]);
  useEffect(() => {
    if (!organizationId) return;
    let active = true;
    portalApi
      .listOperatorBookings(organizationId)
      .then((bookings) => {
        if (active) setItems(bookings);
      })
      .catch(() => {
        if (active) {
          setError(true);
          setItems([]);
        }
      });
    return () => {
      active = false;
    };
  }, [organizationId]);

  if (organizations.length === 0) {
    return (
      <Container>
        <Alert tone="error" title="Operator access required">
          This area is available only to members of an operator organization.
        </Alert>
      </Container>
    );
  }

  async function decide(kind: "confirm" | "reject", bookingId: string) {
    if (guard.current) return;
    guard.current = true;
    setPendingId(bookingId);
    setError(false);
    try {
      if (kind === "confirm")
        await portalApi.confirmOperatorBooking(bookingId, {}, organizationId);
      else
        await portalApi.rejectOperatorBooking(
          bookingId,
          { reason },
          organizationId,
        );
      await load();
      setSelectedId(null);
    } catch (caught) {
      if (activeOrganizationId.current === organizationId) {
        setError(true);
        if (caught instanceof ApiError && caught.status === 409) await load();
      }
    } finally {
      guard.current = false;
      setPendingId(null);
    }
  }

  return (
    <Container>
      <PageHeading
        title="Booking requests"
        description="Pending bookings awaiting your decision."
      />
      {organizations.length > 1 ? (
        <label>
          Operator organization{" "}
          <select
            value={organizationId}
            onChange={(event) => {
              activeOrganizationId.current = event.target.value;
              setItems(null);
              setError(false);
              setSelectedId(null);
              setOrganizationId(event.target.value);
            }}
          >
            <option value="">Choose operator organization</option>
            {organizations.map((org, index) => (
              <option key={org.id} value={org.id}>
                Operator organization {index + 1} — {org.role}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {!organizationId ? (
        <EmptyState
          title="Choose operator organization"
          description="Select the operator organization whose booking requests you want to view."
        />
      ) : error ? (
        <Alert tone="error" title="Booking requests could not be refreshed">
          No decision was retried automatically. Refresh to view the
          authoritative state.
        </Alert>
      ) : null}
      {!organizationId ? null : items === null ? (
        <LoadingState label="Loading booking requests…" />
      ) : items.length === 0 ? (
        <EmptyState
          title="No pending booking requests"
          description="There are no bookings awaiting your decision."
        />
      ) : (
        <div className="operator-booking-list">
          {items.map((booking) => {
            const expanded = selectedId === booking.booking_id;
            const pending = pendingId === booking.booking_id;
            return (
              <Card
                key={booking.booking_id}
                as="article"
                className="operator-booking-card"
              >
                <h2>{booking.reference}</h2>
                <p>
                  <strong>Awaiting your decision</strong>
                </p>
                {booking.legs.map((leg) => (
                  <p key={leg.sequence}>
                    {leg.origin_airport_code} → {leg.destination_airport_code} ·{" "}
                    <time dateTime={leg.departure_at}>
                      {new Date(leg.departure_at).toLocaleString("en-IE")}
                    </time>{" "}
                    · {leg.passenger_count} passengers
                  </p>
                ))}
                <p>
                  {booking.aircraft_manufacturer} {booking.aircraft_model} ·{" "}
                  {booking.aircraft_registration} · {booking.aircraft_category}
                </p>
                <p>
                  Operator amount:{" "}
                  {money(booking.operator_amount_minor, booking.currency)}
                </p>
                {!activeOrganization?.canDecide ? (
                  <p>Read-only access</p>
                ) : !expanded ? (
                  <Button
                    variant="secondary"
                    onClick={() => setSelectedId(booking.booking_id)}
                  >
                    Review decision
                  </Button>
                ) : (
                  <div aria-busy={pending}>
                    <p>
                      Confirming records the operator&apos;s decision. It does
                      not capture payment or ticket the flight.
                    </p>
                    <Button
                      disabled={pending}
                      onClick={() => void decide("confirm", booking.booking_id)}
                    >
                      Confirm booking
                    </Button>
                    <fieldset className="operator-booking-card__rejection">
                      <legend>Reject this booking</legend>
                      <label>
                        Rejection reason{" "}
                        <select
                          disabled={pending}
                          value={reason}
                          onChange={(event) =>
                            setReason(
                              event.target.value as BookingRejectionReason,
                            )
                          }
                        >
                          {REASONS.map((value) => (
                            <option key={value} value={value}>
                              {value.replaceAll("_", " ")}
                            </option>
                          ))}
                        </select>
                      </label>
                      <Button
                        variant="secondary"
                        disabled={pending}
                        onClick={() =>
                          void decide("reject", booking.booking_id)
                        }
                      >
                        Reject booking
                      </Button>
                    </fieldset>
                    <Button
                      variant="ghost"
                      disabled={pending}
                      onClick={() => setSelectedId(null)}
                    >
                      Back
                    </Button>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </Container>
  );
}
