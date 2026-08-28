"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  PlatformPaymentDetail as Detail,
  PlatformPaymentOperation,
} from "@/lib/api/types";

let nextGeneration = 0;

export function PlatformPaymentDetail({
  id,
  canOperate,
}: {
  id: string;
  canOperate: boolean;
}) {
  return <PaymentResource key={id} id={id} canOperate={canOperate} />;
}

function PaymentResource({
  id,
  canOperate,
}: {
  id: string;
  canOperate: boolean;
}) {
  const [generation] = useState(() => ++nextGeneration);
  const identity = useMemo(() => ({ id, generation }), [generation, id]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] =
    useState<PlatformPaymentOperation | null>(null);
  const [busy, setBusy] = useState<symbol | null>(null);
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const requestEpoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mutation = useRef<{
    token: symbol;
    id: string;
    generation: number;
    operationId: string;
  } | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const epoch = ++requestEpoch.current;
    setError(null);
    try {
      const current = await portalApi.getPlatformPayment(
        identity.id,
        next.signal,
      );
      if (epoch === requestEpoch.current && identity.id === id) {
        setDetail(current);
        setRequiresRefresh(false);
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (epoch === requestEpoch.current)
        setError("Authoritative payment detail could not be loaded.");
    }
  }, [id, identity]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      requestEpoch.current += 1;
      controller.current?.abort();
    };
  }, [load]);

  const reconcile = async () => {
    if (!confirmation || mutation.current) return;
    const owner = {
      token: Symbol("payment-reconcile"),
      id,
      generation,
      operationId: confirmation.id,
    };
    mutation.current = owner;
    setBusy(owner.token);
    setError(null);
    try {
      const current = await portalApi.reconcilePlatformPaymentOperation(
        owner.operationId,
      );
      if (
        mutation.current?.token !== owner.token ||
        owner.id !== id ||
        owner.generation !== generation
      )
        return;
      setDetail(current);
      setConfirmation(null);
    } catch (caught) {
      if (
        mutation.current?.token !== owner.token ||
        owner.id !== id ||
        owner.generation !== generation
      )
        return;
      setConfirmation(null);
      if (caught instanceof ApiError && caught.status === 409) {
        await load();
        setError(
          "The operation changed before reconciliation. Current state was refreshed; no retry was sent.",
        );
      } else {
        setRequiresRefresh(true);
        setError(
          "Reconciliation result could not be confirmed. Refresh authoritative state before deciding whether to try again.",
        );
      }
    } finally {
      if (mutation.current?.token === owner.token) mutation.current = null;
      setBusy((current) => (current === owner.token ? null : current));
    }
  };

  const money = (amount: number) =>
    detail
      ? new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: detail.currency,
        }).format(amount / 100)
      : "";
  return (
    <Container>
      <Link href="/platform/payments">← Back to payment exceptions</Link>
      <PageHeading
        title="Payment exception detail"
        description="Provider-neutral operational facts. Captured does not mean settled."
      />
      {error ? (
        <Alert tone="error" title="Reconciliation state">
          <p>{error}</p>
          <Button variant="secondary" onClick={() => void load()}>
            Refresh authoritative state
          </Button>
        </Alert>
      ) : null}
      {!detail ? (
        <LoadingState label="Loading authoritative payment detail…" />
      ) : (
        <>
          <Card className="platform-detail">
            <h2>{detail.reference}</h2>
            <Badge tone="info">{detail.status}</Badge>
            <dl>
              <dt>Payment ID</dt>
              <dd>{detail.id}</dd>
              <dt>Booking ID</dt>
              <dd>{detail.booking_id}</dd>
              <dt>Total</dt>
              <dd>{money(detail.total_amount_minor)}</dd>
              <dt>Authorized</dt>
              <dd>
                {detail.authorized_amount_minor === null
                  ? "Not authorized"
                  : money(detail.authorized_amount_minor)}
              </dd>
              <dt>Captured</dt>
              <dd>{money(detail.captured_amount_minor)}</dd>
              <dt>Refunded</dt>
              <dd>{money(detail.refunded_amount_minor)}</dd>
              <dt>Provider</dt>
              <dd>{detail.payment_provider}</dd>
              <dt>Provider status</dt>
              <dd>{detail.provider_status ?? "Not reported"}</dd>
            </dl>
          </Card>
          <section aria-labelledby="operation-history">
            <h2 id="operation-history">Payment operation timeline</h2>
            {detail.operations.map((operation) => (
              <Card
                key={operation.id}
                as="article"
                className="platform-review-card"
              >
                <div>
                  <h3>{operation.operation}</h3>
                  <Badge tone="info">{operation.result}</Badge>
                </div>
                <p>Operation ID: {operation.id}</p>
                <p>
                  Attempts: {operation.attempt_count} · Updated{" "}
                  {new Date(operation.updated_at).toLocaleString()}
                </p>
                {operation.failure_code ? (
                  <p>Failure classification: {operation.failure_code}</p>
                ) : null}
                {canOperate &&
                operation.result === "UNKNOWN" &&
                operation.operation !== "REFUND" ? (
                  <Button
                    disabled={busy !== null || requiresRefresh}
                    onClick={() => setConfirmation(operation)}
                  >
                    Reconcile existing operation
                  </Button>
                ) : null}
              </Card>
            ))}
          </section>
          {confirmation ? (
            <div
              role="alertdialog"
              aria-labelledby="reconcile-title"
              className="platform-confirm"
              aria-busy={busy !== null}
            >
              <h2 id="reconcile-title">Confirm reconciliation</h2>
              <p>
                Operation {confirmation.id}: {confirmation.operation} is{" "}
                {confirmation.result}. Payment is {detail.status}. Attempts:{" "}
                {confirmation.attempt_count}.
              </p>
              <p>
                This recovery reuses the existing logical operation and provider
                idempotency identity. It does not create a new financial
                attempt.
              </p>
              <Button disabled={busy !== null} onClick={() => void reconcile()}>
                Confirm reconciliation
              </Button>
              <Button
                variant="secondary"
                disabled={busy !== null}
                onClick={() => setConfirmation(null)}
              >
                Cancel
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Container>
  );
}
