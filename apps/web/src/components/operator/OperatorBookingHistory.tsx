"use client";

import Link from "next/link";
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
import type {
  OperatorBookingReadView,
  OperatorBookingStatus,
} from "@/lib/api/types";
import { formatOperatorMoney } from "@/lib/operator/offers";

type Organization = { readonly id: string; readonly role: string };
type Scope = { readonly organizationId: string; readonly epoch: number };

const PAGE_SIZE = 10;
const STATUSES: readonly OperatorBookingStatus[] = [
  "PENDING_OPERATOR_CONFIRMATION",
  "CONFIRMED",
  "REJECTED",
  "CANCELLED",
];

function statusLabel(status: string): string {
  switch (status) {
    case "PENDING_OPERATOR_CONFIRMATION":
      return "Pending operator confirmation";
    case "CONFIRMED":
      return "Booking confirmed";
    case "REJECTED":
      return "Booking rejected";
    case "CANCELLED":
      return "Booking cancelled";
    default:
      return "Status unavailable";
  }
}

function lifecycleTime(item: OperatorBookingReadView): {
  label: string;
  value: string;
} | null {
  if (item.status === "CONFIRMED" && item.confirmed_at)
    return { label: "Confirmed", value: item.confirmed_at };
  if (item.status === "REJECTED" && item.rejected_at)
    return { label: "Rejected", value: item.rejected_at };
  if (item.status === "CANCELLED" && item.cancelled_at)
    return { label: "Cancelled", value: item.cancelled_at };
  return null;
}

function dateTime(value: string): string {
  return new Date(value).toLocaleString("en-IE");
}

function BookingFacts({ item }: { readonly item: OperatorBookingReadView }) {
  const lifecycle = lifecycleTime(item);
  return (
    <dl className="operator-history__facts">
      {item.legs.map((leg) => (
        <div key={leg.sequence} className="operator-history__leg">
          <dt>Route</dt>
          <dd>
            <strong>
              {leg.origin_airport_code} → {leg.destination_airport_code}
            </strong>
          </dd>
          <dt>Departure</dt>
          <dd>
            <time dateTime={leg.departure_at}>
              {dateTime(leg.departure_at)}
            </time>
          </dd>
          <dt>Passengers</dt>
          <dd>{leg.passenger_count}</dd>
        </div>
      ))}
      <div>
        <dt>Aircraft</dt>
        <dd>
          {item.aircraft_manufacturer} {item.aircraft_model} ·{" "}
          {item.aircraft_registration} · {item.aircraft_category}
        </dd>
      </div>
      <div>
        <dt>Operator amount</dt>
        <dd>
          {formatOperatorMoney(item.operator_amount_minor, item.currency)}
        </dd>
      </div>
      <div>
        <dt>Created</dt>
        <dd>
          <time dateTime={item.created_at}>{dateTime(item.created_at)}</time>
        </dd>
      </div>
      {lifecycle ? (
        <div>
          <dt>{lifecycle.label}</dt>
          <dd>
            <time dateTime={lifecycle.value}>{dateTime(lifecycle.value)}</time>
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

export function OperatorBookingHistory({
  organizations,
  bookingId,
}: {
  readonly organizations: readonly Organization[];
  readonly bookingId?: string;
}) {
  const [organizationId, setOrganizationId] = useState(
    organizations.length === 1 ? organizations[0].id : "",
  );
  const [items, setItems] = useState<readonly OperatorBookingReadView[] | null>(
    null,
  );
  const [detail, setDetail] = useState<OperatorBookingReadView | null>(null);
  const [status, setStatus] = useState<OperatorBookingStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<"not-found" | "read" | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);
  const organizationRef = useRef(organizationId);

  function isCurrent(scope: Scope): boolean {
    return (
      scope.organizationId === organizationRef.current &&
      scope.epoch === epochRef.current
    );
  }

  const clearScope = useCallback((nextOrganizationId: string) => {
    controllerRef.current?.abort();
    organizationRef.current = nextOrganizationId;
    epochRef.current += 1;
    setItems(null);
    setDetail(null);
    setError(null);
    setOffset(0);
  }, []);

  const load = useCallback(async () => {
    const orgId = organizationRef.current;
    if (!orgId) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const scope = { organizationId: orgId, epoch: ++epochRef.current };
    setError(null);
    if (bookingId) setDetail(null);
    else setItems(null);
    try {
      if (bookingId) {
        const next = await portalApi.getOperatorBooking(
          bookingId,
          orgId,
          controller.signal,
        );
        if (isCurrent(scope)) setDetail(next);
      } else {
        const next = await portalApi.listOperatorBookingHistory(
          orgId,
          { limit: PAGE_SIZE, offset, status: status || undefined },
          controller.signal,
        );
        if (isCurrent(scope)) setItems(next);
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (!isCurrent(scope)) return;
      setError(
        caught instanceof ApiError && caught.status === 404
          ? "not-found"
          : "read",
      );
      if (bookingId) setDetail(null);
      else setItems([]);
    }
  }, [bookingId, offset, status]);

  useEffect(() => {
    if (!organizationId) return;
    let active = true;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      controllerRef.current?.abort();
    };
  }, [organizationId, load]);

  if (organizations.length === 0)
    return (
      <Container>
        <Alert tone="error" title="Operator access required">
          This area is available only to members of an operator organization.
        </Alert>
      </Container>
    );

  const heading = bookingId ? "Booking detail" : "Booking history";
  return (
    <div className="operator operator-history">
      <Container>
        <PageHeading
          title={heading}
          description={
            bookingId
              ? "Authoritative operator-safe booking facts."
              : "Bounded history across canonical booking lifecycle states."
          }
        />
        <div className="operator-history__links">
          <Link href="/operator/bookings">Pending bookings</Link>
          {bookingId ? (
            <>
              <Link href="/operator/bookings/history">Back to history</Link>
              <Button
                variant="secondary"
                disabled={!organizationId}
                onClick={() => void load()}
              >
                Refresh
              </Button>
            </>
          ) : null}
        </div>
        {organizations.length > 1 ? (
          <label className="operator-org">
            Operator organization{" "}
            <select
              className="operator-org__select"
              value={organizationId}
              onChange={(event) => {
                const next = event.target.value;
                clearScope(next);
                setOrganizationId(next);
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
        {!bookingId ? (
          <div
            className="operator-history__toolbar"
            role="region"
            aria-label="History controls"
          >
            <label>
              Booking status{" "}
              <select
                value={status}
                onChange={(event) => {
                  setOffset(0);
                  setStatus(event.target.value as OperatorBookingStatus | "");
                }}
              >
                <option value="">All statuses</option>
                {STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {statusLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="secondary"
              disabled={!organizationId}
              onClick={() => void load()}
            >
              Refresh
            </Button>
          </div>
        ) : null}
        {!organizationId ? (
          <EmptyState
            title="Choose operator organization"
            description="Select the operator organization whose bookings you want to view."
          />
        ) : error === "not-found" ? (
          <Alert tone="error" title="Booking not found">
            This booking is unavailable in the active operator organization.
          </Alert>
        ) : error === "read" ? (
          <Alert tone="error" title="Booking information could not be loaded">
            No action was attempted. Use Refresh or try again later.
          </Alert>
        ) : bookingId && detail === null ? (
          <LoadingState label="Loading booking detail…" />
        ) : bookingId && detail ? (
          <Card as="article" className="operator-history__detail">
            <header className="operator-history__head">
              <h2>{detail.reference}</h2>
              <strong>{statusLabel(detail.status)}</strong>
            </header>
            <BookingFacts item={detail} />
            {detail.status === "PENDING_OPERATOR_CONFIRMATION" ? (
              <p>
                Decisions remain in the{" "}
                <Link href="/operator/bookings">pending queue</Link>.
              </p>
            ) : null}
          </Card>
        ) : items === null ? (
          <LoadingState label="Loading booking history…" />
        ) : items.length === 0 ? (
          <EmptyState
            title="No booking history"
            description="No bookings match the active organization and status filter."
          />
        ) : (
          <>
            <div className="operator-history__list" aria-live="polite">
              {items.map((item) => (
                <Card
                  key={item.id}
                  as="article"
                  className="operator-history__card"
                >
                  <header className="operator-history__head">
                    <h2>{item.reference}</h2>
                    <strong>{statusLabel(item.status)}</strong>
                  </header>
                  <BookingFacts item={item} />
                  <Link href={`/operator/bookings/${item.id}`}>
                    View booking detail
                  </Link>
                </Card>
              ))}
            </div>
            <nav
              className="operator-history__pagination"
              aria-label="Booking history pages"
            >
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() =>
                  setOffset((current) => Math.max(0, current - PAGE_SIZE))
                }
              >
                Previous
              </Button>
              <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
              <Button
                variant="secondary"
                disabled={items.length < PAGE_SIZE}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Next
              </Button>
            </nav>
          </>
        )}
      </Container>
    </div>
  );
}
