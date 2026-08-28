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
  ComplianceAuditEvent,
  PlatformAdmission,
  PlatformAuthorization,
  PlatformEvidence,
} from "@/lib/api/types";

type Kind = "admissions" | "evidence" | "aircraft-authorizations";
type Detail = PlatformAdmission | PlatformEvidence | PlatformAuthorization;
interface ResourceIdentity {
  readonly kind: Kind;
  readonly id: string;
  readonly generation: number;
}
interface ConfirmationIdentity extends ResourceIdentity {
  readonly action: string;
}
interface MutationIdentity extends ConfirmationIdentity {
  readonly token: symbol;
}

function sameResource(left: ResourceIdentity, right: ResourceIdentity) {
  return (
    left.kind === right.kind &&
    left.id === right.id &&
    left.generation === right.generation
  );
}

let nextDetailGeneration = 0;

function createDetailGeneration() {
  nextDetailGeneration += 1;
  return nextDetailGeneration;
}

function actions(kind: Kind, status: string): readonly string[] {
  if (status === "SUBMITTED") return ["BEGIN_REVIEW"];
  if (status === "UNDER_REVIEW")
    return kind === "evidence" ? ["VERIFY", "REJECT"] : ["APPROVE", "REJECT"];
  if (kind !== "evidence" && status === "APPROVED") return ["SUSPEND"];
  if (kind !== "evidence" && status === "SUSPENDED") return ["RESTORE"];
  return [];
}

export function PlatformComplianceDetail({
  kind,
  id,
}: {
  kind: Kind;
  id: string;
}) {
  return (
    <PlatformComplianceResource key={`${kind}:${id}`} kind={kind} id={id} />
  );
}

function PlatformComplianceResource({ kind, id }: { kind: Kind; id: string }) {
  const [generation] = useState(createDetailGeneration);
  const identity = useMemo<ResourceIdentity>(
    () => ({ kind, id, generation }),
    [generation, id, kind],
  );
  const [detail, setDetail] = useState<Detail | null>(null);
  const [audit, setAudit] = useState<readonly ComplianceAuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<ConfirmationIdentity | null>(
    null,
  );
  const [note, setNote] = useState("");
  const [busyToken, setBusyToken] = useState<symbol | null>(null);
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const requestEpoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mutation = useRef<MutationIdentity | null>(null);
  const busy = busyToken !== null;

  const load = useCallback(
    async (owner: ResourceIdentity) => {
      controller.current?.abort();
      const next = new AbortController();
      controller.current = next;
      const epoch = ++requestEpoch.current;
      setError(null);
      try {
        const resource =
          owner.kind === "admissions"
            ? await portalApi.getPlatformAdmission(owner.id, next.signal)
            : owner.kind === "evidence"
              ? await portalApi.getPlatformEvidence(owner.id, next.signal)
              : await portalApi.getPlatformAuthorization(owner.id, next.signal);
        if (epoch !== requestEpoch.current || !sameResource(owner, identity))
          return;
        setDetail(resource);
        const events = await portalApi.listPlatformComplianceAudit(
          owner.kind,
          owner.id,
          next.signal,
        );
        if (epoch === requestEpoch.current && sameResource(owner, identity)) {
          setAudit(events);
          setRequiresRefresh(false);
        }
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError")
          return;
        if (epoch === requestEpoch.current && sameResource(owner, identity)) {
          setError("Authoritative review detail could not be loaded.");
          setRequiresRefresh(true);
        }
      }
    },
    [identity],
  );

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void load(identity);
    });
    return () => {
      active = false;
      requestEpoch.current += 1;
      controller.current?.abort();
    };
  }, [identity, load]);

  const confirm = async () => {
    const selected = confirmation;
    if (!selected || !sameResource(selected, identity) || mutation.current)
      return;
    const operation: MutationIdentity = {
      ...selected,
      token: Symbol("platform-compliance-mutation"),
    };
    mutation.current = operation;
    setBusyToken(operation.token);
    setError(null);
    try {
      const body = {
        action: operation.action,
        ...(note.trim() ? { note: note.trim() } : {}),
      };
      const updated =
        operation.kind === "admissions"
          ? await portalApi.reviewPlatformAdmission(operation.id, body)
          : operation.kind === "evidence"
            ? await portalApi.reviewPlatformEvidence(operation.id, body)
            : await portalApi.reviewPlatformAuthorization(operation.id, body);
      if (
        mutation.current?.token !== operation.token ||
        !sameResource(operation, identity)
      )
        return;
      setDetail(updated);
      setConfirmation(null);
      setNote("");
      await load(operation);
    } catch (caught) {
      if (
        mutation.current?.token !== operation.token ||
        !sameResource(operation, identity)
      )
        return;
      setConfirmation(null);
      setNote("");
      if (caught instanceof ApiError && caught.status === 409) {
        await load(operation);
        if (!sameResource(operation, identity)) return;
        setError(
          "The resource changed before this decision. The authoritative state was refreshed; the decision was not retried.",
        );
      } else {
        setRequiresRefresh(true);
        setError(
          "The decision outcome is not confirmed. Refresh before deciding whether to try again.",
        );
      }
    } finally {
      if (mutation.current?.token === operation.token) mutation.current = null;
      setBusyToken((current) => (current === operation.token ? null : current));
    }
  };

  return (
    <Container>
      <Link href="/platform/compliance">← Back to compliance queues</Link>
      <PageHeading
        title="Compliance review detail"
        description="Marketplace eligibility governance; not a regulator certification."
      />
      {error ? (
        <Alert tone="error" title="Review state">
          <p>{error}</p>
          <Button variant="secondary" onClick={() => void load(identity)}>
            Refresh authoritative state
          </Button>
        </Alert>
      ) : null}
      {!detail ? (
        <LoadingState label="Loading authoritative detail…" />
      ) : (
        <>
          <Card className="platform-detail">
            <h2>{detail.operator_legal_name}</h2>
            <Badge tone="info">{detail.status.replaceAll("_", " ")}</Badge>
            <dl>
              <dt>Resource ID</dt>
              <dd>{detail.id}</dd>
              <dt>Operator ID</dt>
              <dd>{detail.operator_id}</dd>
              {"evidence_type" in detail ? (
                <>
                  <dt>Evidence</dt>
                  <dd>{detail.evidence_type.replaceAll("_", " ")}</dd>
                  <dt>Document metadata supplied</dt>
                  <dd>
                    {detail.has_storage_object
                      ? "Yes — opaque reference retained server-side"
                      : "No"}
                  </dd>
                  <dt>Reference</dt>
                  <dd>{detail.reference_number ?? "Not provided"}</dd>
                  <dt>Issuer</dt>
                  <dd>
                    {detail.issuing_authority ??
                      detail.insurer_name ??
                      "Not provided"}
                  </dd>
                </>
              ) : null}
              {"aircraft_registration" in detail &&
              detail.aircraft_registration ? (
                <>
                  <dt>Aircraft</dt>
                  <dd>
                    {detail.aircraft_registration}
                    {"aircraft_model" in detail
                      ? ` — ${detail.aircraft_manufacturer} ${detail.aircraft_model}`
                      : ""}
                  </dd>
                </>
              ) : null}
              <dt>Submitted</dt>
              <dd>
                {detail.submitted_at
                  ? new Date(detail.submitted_at).toLocaleString()
                  : "Not submitted"}
              </dd>
            </dl>
          </Card>
          <Card className="platform-decision" aria-busy={busy}>
            <h2>Review decision</h2>
            {actions(kind, detail.status).length === 0 ? (
              <p>No review transition is available from the current state.</p>
            ) : (
              <div className="platform-actions">
                {actions(kind, detail.status).map((action) => (
                  <Button
                    key={action}
                    variant={
                      action === "REJECT" || action === "SUSPEND"
                        ? "secondary"
                        : "primary"
                    }
                    disabled={busy || requiresRefresh}
                    onClick={() => {
                      setNote("");
                      setConfirmation({ ...identity, action });
                    }}
                  >
                    {action.replaceAll("_", " ")}
                  </Button>
                ))}
              </div>
            )}
            {confirmation && sameResource(confirmation, identity) ? (
              <div
                className="platform-confirm"
                role="alertdialog"
                aria-labelledby="confirm-title"
              >
                <h3 id="confirm-title">
                  Confirm{" "}
                  {confirmation.action.replaceAll("_", " ").toLowerCase()}
                </h3>
                <p>
                  This decision affects Sky Bridge Jet marketplace eligibility
                  for {detail.operator_legal_name}.
                </p>
                <p>
                  Resource {detail.id}. Current status:{" "}
                  {detail.status.replaceAll("_", " ")}.
                </p>
                <label htmlFor="review-note">
                  Internal review note (optional)
                </label>
                <textarea
                  id="review-note"
                  maxLength={500}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
                <div>
                  <Button disabled={busy} onClick={() => void confirm()}>
                    Confirm decision
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => {
                      setConfirmation(null);
                      setNote("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
          <Card className="platform-audit">
            <h2>Decision history</h2>
            {audit.length === 0 ? (
              <p>No audit events.</p>
            ) : (
              <ol>
                {audit.map((event) => (
                  <li key={event.id}>
                    <strong>{event.action.replaceAll("_", " ")}</strong> —{" "}
                    {new Date(event.created_at).toLocaleString()}
                    <span>
                      {event.previous_status ?? "Created"} →{" "}
                      {event.new_status ?? "Unchanged"}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </>
      )}
    </Container>
  );
}
