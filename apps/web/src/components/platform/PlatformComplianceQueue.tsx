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

type Kind = "admissions" | "evidence" | "aircraft-authorizations";
interface QueueItem {
  readonly id: string;
  readonly operator_legal_name: string;
  readonly status: string;
  readonly submitted_at: string | null;
  readonly evidence_type?: string;
  readonly aircraft_registration?: string | null;
}

const PAGE_SIZE = 20;
const labels: Record<Kind, string> = {
  admissions: "Admissions",
  evidence: "Evidence",
  "aircraft-authorizations": "Aircraft authorizations",
};
const defaults: Record<Kind, string> = {
  admissions: "SUBMITTED",
  evidence: "SUBMITTED",
  "aircraft-authorizations": "SUBMITTED",
};

export function PlatformComplianceQueue() {
  const [kind, setKind] = useState<Kind>("admissions");
  const [status, setStatus] = useState(defaults.admissions);
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<readonly QueueItem[] | null>(null);
  const [error, setError] = useState(false);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    const request = ++epoch.current;
    setItems(null);
    setError(false);
    const query = { status: status || undefined, limit: PAGE_SIZE, offset };
    try {
      const result =
        kind === "admissions"
          ? await portalApi.listPlatformAdmissions(query, nextController.signal)
          : kind === "evidence"
            ? await portalApi.listPlatformEvidence(query, nextController.signal)
            : await portalApi.listPlatformAuthorizations(
                query,
                nextController.signal,
              );
      if (request === epoch.current) setItems(result);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (request === epoch.current) setError(true);
    }
  }, [kind, offset, status]);

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

  const changeKind = (next: Kind) => {
    controller.current?.abort();
    epoch.current += 1;
    setKind(next);
    setStatus(defaults[next]);
    setOffset(0);
    setItems(null);
    setError(false);
  };

  return (
    <Container>
      <PageHeading
        title="Compliance review"
        description="Bounded internal queues for Sky Bridge Jet marketplace eligibility decisions."
      />
      <div
        className="platform-tabs"
        role="tablist"
        aria-label="Compliance resource"
      >
        {(Object.keys(labels) as Kind[]).map((value) => (
          <Button
            key={value}
            variant={kind === value ? "primary" : "secondary"}
            role="tab"
            aria-selected={kind === value}
            onClick={() => changeKind(value)}
          >
            {labels[value]}
          </Button>
        ))}
      </div>
      <div className="platform-toolbar">
        <label htmlFor="review-status">Status</label>
        <select
          id="review-status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setOffset(0);
          }}
        >
          <option value="">All statuses</option>
          <option value="SUBMITTED">Submitted</option>
          <option value="UNDER_REVIEW">Under review</option>
          <option value="APPROVED">Approved</option>
          <option value="VERIFIED">Verified</option>
          <option value="REJECTED">Rejected</option>
          <option value="SUSPENDED">Suspended</option>
        </select>
        <Button
          variant="secondary"
          onClick={() => void load()}
          disabled={items === null}
        >
          Refresh
        </Button>
      </div>
      {error ? (
        <Alert tone="error" title="Queue unavailable">
          <Button variant="secondary" onClick={() => void load()}>
            Try again
          </Button>
        </Alert>
      ) : null}
      {!error && items === null ? (
        <LoadingState label={`Loading ${labels[kind].toLowerCase()}…`} />
      ) : null}
      {!error && items?.length === 0 ? (
        <EmptyState
          title="No matching review work"
          description="Change the status filter or refresh this bounded queue."
        />
      ) : null}
      {items && items.length > 0 ? (
        <div className="platform-review-list" aria-live="polite">
          {items.map((item) => (
            <Card key={item.id} as="article" className="platform-review-card">
              <div>
                <h2>{item.operator_legal_name}</h2>
                <Badge tone="info">{item.status.replaceAll("_", " ")}</Badge>
              </div>
              <p>
                {item.evidence_type?.replaceAll("_", " ") ??
                  item.aircraft_registration ??
                  labels[kind].slice(0, -1)}
              </p>
              <p>
                Submitted:{" "}
                {item.submitted_at
                  ? new Date(item.submitted_at).toLocaleString()
                  : "Not submitted"}
              </p>
              <Link href={`/platform/compliance/${kind}/${item.id}`}>
                Open review detail
              </Link>
            </Card>
          ))}
        </div>
      ) : null}
      <nav className="platform-pagination" aria-label="Review queue pages">
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
