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
import type { OperatorFlightOperation } from "@/lib/api/types";

type Organization = { readonly id: string; readonly role: string };
type Scope = {
  readonly organizationId: string;
  readonly epoch: number;
  readonly requestId: number;
  readonly offset: number;
};
const PAGE_SIZE = 20;

function dateTime(value: string): string {
  return new Date(value).toLocaleString("en-IE");
}

function operationStatus(status: string): string {
  return status === "HANDOFF_CREATED"
    ? "Operational handoff created"
    : "Operational status unavailable";
}

function bookingStatus(status: string): string {
  switch (status) {
    case "CONFIRMED":
      return "Confirmed";
    case "CANCELLED":
      return "Cancelled";
    case "REJECTED":
      return "Rejected";
    case "PENDING_OPERATOR_CONFIRMATION":
      return "Pending operator confirmation";
    default:
      return "Status unavailable";
  }
}

function OperationFacts({
  item,
  detail = false,
}: {
  readonly item: OperatorFlightOperation;
  readonly detail?: boolean;
}) {
  return (
    <>
      <dl className="operator-operations__facts">
        <div>
          <dt>Operation status</dt>
          <dd>{operationStatus(item.status)}</dd>
        </div>
        <div>
          <dt>Booking status</dt>
          <dd>{bookingStatus(item.booking_status)}</dd>
        </div>
        <div>
          <dt>Contractual aircraft</dt>
          <dd>
            {item.aircraft_manufacturer} {item.aircraft_model} ·{" "}
            {item.aircraft_registration} · {item.aircraft_category}
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>
            <time dateTime={item.created_at}>{dateTime(item.created_at)}</time>
          </dd>
        </div>
        {detail ? (
          <div>
            <dt>Updated</dt>
            <dd>
              <time dateTime={item.updated_at}>
                {dateTime(item.updated_at)}
              </time>
            </dd>
          </div>
        ) : null}
      </dl>
      <section aria-labelledby={`legs-${item.operation_id}`}>
        <h3 id={`legs-${item.operation_id}`}>Planned legs</h3>
        <div className="operator-operations__legs">
          {item.legs.map((leg) => (
            <article key={leg.sequence} className="operator-operations__leg">
              <h4>Leg {leg.sequence}</h4>
              <dl>
                <div>
                  <dt>Route</dt>
                  <dd>
                    {leg.origin_airport_code} → {leg.destination_airport_code}
                  </dd>
                </div>
                <div>
                  <dt>Scheduled departure</dt>
                  <dd>
                    <time dateTime={leg.departure_at}>
                      {dateTime(leg.departure_at)}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>Passenger count</dt>
                  <dd>{leg.passenger_count}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>
      {item.booking_status === "CANCELLED" ? (
        <p>
          <strong>Booking status: Cancelled.</strong> Operational handoff record
          retained for history.
        </p>
      ) : null}
    </>
  );
}

export function OperatorOperations({
  organizations,
  operationId,
}: {
  readonly organizations: readonly Organization[];
  readonly operationId?: string;
}) {
  const [organizationId, setOrganizationId] = useState(
    organizations.length === 1 ? organizations[0].id : "",
  );
  const [items, setItems] = useState<readonly OperatorFlightOperation[] | null>(
    null,
  );
  const [detail, setDetail] = useState<OperatorFlightOperation | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<"not-found" | "read" | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);
  const requestRef = useRef(0);
  const organizationRef = useRef(organizationId);

  const current = useCallback(
    (scope: Scope) =>
      scope.organizationId === organizationRef.current &&
      scope.epoch === epochRef.current &&
      scope.requestId === requestRef.current &&
      (operationId !== undefined || scope.offset === offset),
    [offset, operationId],
  );

  const clearScope = useCallback((next: string) => {
    controllerRef.current?.abort();
    organizationRef.current = next;
    epochRef.current += 1;
    requestRef.current += 1;
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
    const scope = {
      organizationId: orgId,
      epoch: epochRef.current,
      requestId: ++requestRef.current,
      offset,
    };
    setError(null);
    if (operationId) setDetail(null);
    else setItems(null);
    try {
      const next = operationId
        ? await portalApi.getOperatorOperation(
            operationId,
            orgId,
            controller.signal,
          )
        : await portalApi.listOperatorOperations(
            orgId,
            { limit: PAGE_SIZE, offset },
            controller.signal,
          );
      if (!current(scope)) return;
      if (operationId) setDetail(next as OperatorFlightOperation);
      else {
        const page = next as readonly OperatorFlightOperation[];
        if (page.length === 0 && offset > 0) {
          setOffset(Math.max(0, offset - PAGE_SIZE));
          return;
        }
        setItems(page);
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (!current(scope)) return;
      setError(
        caught instanceof ApiError && caught.status === 404
          ? "not-found"
          : "read",
      );
      if (operationId) setDetail(null);
      else setItems([]);
    }
  }, [current, offset, operationId]);

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
  return (
    <div className="operator operator-operations">
      <Container>
        <PageHeading
          title={operationId ? "Operation detail" : "Operations"}
          description="Read-only operational handoff facts for confirmed bookings."
        />
        <p className="operator-operations__note">
          Sky Bridge Jet currently records the handoff of a confirmed Booking
          into the operational stage. Detailed dispatch, crew, handling,
          departure and arrival states are not yet tracked in this workspace.
        </p>
        <div className="operator-operations__toolbar">
          {operationId ? (
            <Link href="/operator/operations">Back to operations</Link>
          ) : (
            <Link href="/operator/bookings">Pending bookings</Link>
          )}
          <Button
            variant="secondary"
            disabled={!organizationId}
            onClick={() => void load()}
          >
            Refresh
          </Button>
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
        {!organizationId ? (
          <EmptyState
            title="Choose operator organization"
            description="Select the operator organization whose operational handoffs you want to view."
          />
        ) : error === "not-found" ? (
          <Alert tone="error" title="Operation not found">
            This operation is unavailable in the active operator organization.
          </Alert>
        ) : error === "read" ? (
          <Alert tone="error" title="Operations could not be loaded">
            No action was attempted. Use Refresh or try again later.
          </Alert>
        ) : operationId && detail === null ? (
          <LoadingState label="Loading operation detail…" />
        ) : operationId && detail ? (
          <Card as="article" className="operator-operations__detail">
            <header>
              <div>
                <p>Booking reference</p>
                <h2>{detail.booking_reference}</h2>
              </div>
              <strong>{operationStatus(detail.status)}</strong>
            </header>
            <p className="operator-operations__identity">
              Operation {detail.operation_id}
            </p>
            <OperationFacts item={detail} detail />
          </Card>
        ) : items === null ? (
          <LoadingState label="Loading operations…" />
        ) : items.length === 0 ? (
          <EmptyState
            title="No operational handoffs"
            description="No confirmed bookings have an operational handoff on this page for the active organization."
          />
        ) : (
          <>
            <div className="operator-operations__list" aria-live="polite">
              {items.map((item) => (
                <Card
                  key={item.operation_id}
                  as="article"
                  className="operator-operations__card"
                >
                  <header>
                    <div>
                      <p>Booking reference</p>
                      <h2>{item.booking_reference}</h2>
                    </div>
                    <strong>{operationStatus(item.status)}</strong>
                  </header>
                  <OperationFacts item={item} />
                  <Link href={`/operator/operations/${item.operation_id}`}>
                    View operation detail
                  </Link>
                </Card>
              ))}
            </div>
            <nav
              className="operator-operations__pagination"
              aria-label="Operation pages"
            >
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() =>
                  setOffset((value) => Math.max(0, value - PAGE_SIZE))
                }
              >
                Previous
              </Button>
              <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
              <Button
                variant="secondary"
                disabled={items.length < PAGE_SIZE}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
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
