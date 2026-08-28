"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  EmptyState,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import type {
  PaymentOperationResult,
  PaymentOperationType,
  PlatformPaymentException,
} from "@/lib/api/types";

const PAGE_SIZE = 20;

export function PlatformPaymentExceptions() {
  const [result, setResult] = useState<PaymentOperationResult | "">("");
  const [operation, setOperation] = useState<PaymentOperationType | "">("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<
    readonly PlatformPaymentException[] | null
  >(null);
  const [error, setError] = useState(false);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const request = ++epoch.current;
    setItems(null);
    setError(false);
    try {
      const rows = await portalApi.listPlatformPaymentExceptions(
        {
          result: result ? [result] : undefined,
          operation: operation || undefined,
          limit: PAGE_SIZE,
          offset,
        },
        next.signal,
      );
      if (request === epoch.current) setItems(rows);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (request === epoch.current) setError(true);
    }
  }, [offset, operation, result]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, [load]);

  return (
    <Container>
      <PageHeading
        title="Payment exceptions"
        description="Bounded operational review of unresolved and failed payment operations."
      />
      <div className="platform-toolbar">
        <label htmlFor="payment-result">Operation result</label>
        <select
          id="payment-result"
          value={result}
          onChange={(event) => {
            setResult(event.target.value as PaymentOperationResult | "");
            setOffset(0);
          }}
        >
          <option value="">Unresolved and failed</option>
          <option value="UNKNOWN">Unknown</option>
          <option value="PENDING">Pending</option>
          <option value="FAILED">Failed</option>
          <option value="SUCCEEDED">Succeeded</option>
        </select>
        <label htmlFor="payment-operation">Operation</label>
        <select
          id="payment-operation"
          value={operation}
          onChange={(event) => {
            setOperation(event.target.value as PaymentOperationType | "");
            setOffset(0);
          }}
        >
          <option value="">All operations</option>
          <option value="AUTHORIZE">Authorize</option>
          <option value="CAPTURE">Capture</option>
          <option value="VOID">Void</option>
          <option value="REFUND">Refund</option>
        </select>
        <Button
          variant="secondary"
          disabled={items === null}
          onClick={() => void load()}
        >
          Refresh
        </Button>
      </div>
      {error ? (
        <Alert tone="error" title="Payment exceptions unavailable">
          <Button variant="secondary" onClick={() => void load()}>
            Try again
          </Button>
        </Alert>
      ) : null}
      {!error && items === null ? (
        <LoadingState label="Loading payment exceptions…" />
      ) : null}
      {!error && items?.length === 0 ? (
        <EmptyState
          title="No matching exceptions"
          description="Change the filters or refresh this bounded queue."
        />
      ) : null}
      {items?.map((item) => (
        <Card key={item.id} as="article" className="platform-review-card">
          <div>
            <h2>{item.payment_reference}</h2>
            <Badge tone="info">{item.result}</Badge>
          </div>
          <p>
            {item.operation} · Payment {item.payment_status}
          </p>
          <p>
            {new Intl.NumberFormat(undefined, {
              style: "currency",
              currency: item.currency,
            }).format(item.total_amount_minor / 100)}
          </p>
          <p>
            Attempts: {item.attempt_count} · Updated{" "}
            {new Date(item.updated_at).toLocaleString()}
          </p>
          <Link href={`/platform/payments/${item.payment_id}`}>
            Open payment detail
          </Link>
        </Card>
      ))}
      <nav className="platform-pagination" aria-label="Payment exception pages">
        <Button
          variant="secondary"
          disabled={offset === 0 || items === null}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </Button>
        <span>
          Items {offset + 1}–{offset + (items?.length ?? 0)}
        </span>
        <Button
          variant="secondary"
          disabled={!items || items.length < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </Button>
      </nav>
    </Container>
  );
}
