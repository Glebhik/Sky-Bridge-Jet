"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  EmptyState,
  Field,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/errors";
import { portalApi } from "@/lib/api/client";
import type {
  PilotAudit,
  PilotMode,
  PilotParticipant,
  PilotParticipantStatus,
  PilotReason,
  PilotState,
} from "@/lib/api/types";

const PAGE_SIZE = 20;

export function PlatformPilotGovernance({ canManage }: { canManage: boolean }) {
  const [state, setState] = useState<PilotState | null>(null);
  const [participants, setParticipants] = useState<
    readonly PilotParticipant[] | null
  >(null);
  const [audits, setAudits] = useState<readonly PilotAudit[]>([]);
  const [organizationId, setOrganizationId] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const request = ++epoch.current;
    setError("");
    setParticipants(null);
    try {
      const [pilotState, rows, events] = await Promise.all([
        portalApi.getPilotState(next.signal),
        portalApi.listPilotParticipants(offset, next.signal),
        portalApi.listPilotAudits(next.signal),
      ]);
      if (request !== epoch.current) return;
      setState(pilotState);
      setParticipants(rows);
      setAudits(events);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError")
        return;
      if (request === epoch.current)
        setError(
          "Pilot governance is unavailable. Refresh before making a decision.",
        );
    }
  }, [offset]);

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

  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setError("");
    let outcomeMessage = "";
    try {
      await action();
    } catch (caught) {
      outcomeMessage =
        caught instanceof ApiError && caught.status === 409
          ? "The authoritative state changed. It has been refreshed; review it before retrying."
          : "The result is unknown or the command failed. Authoritative state has been refreshed; no command was retried.";
    } finally {
      setBusy(false);
      await load();
      if (outcomeMessage) setError(outcomeMessage);
    }
  };

  const changeMode = (mode: PilotMode) => {
    if (
      !state ||
      !window.confirm(
        `Change pilot mode to ${mode}? Existing records will not be changed.`,
      )
    )
      return;
    void run(() =>
      portalApi.updatePilotState({
        mode,
        payment_initiation_enabled: state.payment_initiation_enabled,
        expected_version: state.version,
        reason: mode === "PAUSED" ? "OPERATIONAL_PAUSE" : "OWNER_APPROVED",
      }),
    );
  };

  const changeParticipant = (
    item: PilotParticipant,
    status: PilotParticipantStatus,
    reason: PilotReason,
  ) => {
    if (
      !window.confirm(`${status} pilot access for ${item.organization_name}?`)
    )
      return;
    void run(() =>
      portalApi.updatePilotParticipant(item.id, {
        status,
        expected_version: item.version,
        reason,
      }),
    );
  };

  return (
    <Container>
      <PageHeading
        title="Controlled pilot governance"
        description="Invite-only participation and fail-closed controls for new pilot journeys."
      />
      {error ? (
        <Alert tone="error" title="Review required">
          {error}
        </Alert>
      ) : null}
      {!state || participants === null ? (
        <LoadingState label="Loading authoritative pilot state…" />
      ) : null}
      {state ? (
        <Card className="platform-detail">
          <h2>Global controls</h2>
          <p>
            <Badge tone={state.mode === "PAUSED" ? "danger" : "info"}>
              {state.mode}
            </Badge>{" "}
            · Payment initiation{" "}
            {state.payment_initiation_enabled ? "enabled" : "paused"}
          </p>
          {state.mode === "CONTROLLED_EXTERNAL" ? (
            <p>
              Controlled external pilot access is invite-only and operates with
              NO REAL MONEY.
            </p>
          ) : null}
          {state.mode === "PAUSED" ? (
            <p>
              New controlled journeys are paused. Existing bookings remain
              unchanged.
            </p>
          ) : null}
          {!canManage ? (
            <p>Read-only access. Governance changes require pilot.manage.</p>
          ) : null}
          {canManage ? (
            <div className="platform-actions" aria-label="Pilot mode controls">
              {(
                ["INTERNAL_ONLY", "CONTROLLED_EXTERNAL", "PAUSED"] as const
              ).map((mode) => (
                <Button
                  key={mode}
                  variant="secondary"
                  disabled={busy || state.mode === mode}
                  onClick={() => changeMode(mode)}
                >
                  {mode}
                </Button>
              ))}
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  if (
                    !window.confirm(
                      `${state.payment_initiation_enabled ? "Pause" : "Enable"} test payment initiation? No live payment mode is enabled.`,
                    )
                  )
                    return;
                  void run(() =>
                    portalApi.updatePilotState({
                      mode: state.mode,
                      payment_initiation_enabled:
                        !state.payment_initiation_enabled,
                      expected_version: state.version,
                      reason: "OWNER_APPROVED",
                    }),
                  );
                }}
              >
                {state.payment_initiation_enabled
                  ? "Pause payment initiation"
                  : "Enable test payment initiation"}
              </Button>
            </div>
          ) : null}
        </Card>
      ) : null}
      {canManage ? (
        <Card className="platform-decision">
          <h2>Invite an existing organization</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (
                !organizationId ||
                !window.confirm(
                  "Invite this exact existing organization to the controlled pilot?",
                )
              )
                return;
              void run(async () => {
                await portalApi.createPilotParticipant(organizationId);
                setOrganizationId("");
              });
            }}
          >
            <Field
              id="pilot-organization"
              label="Organization UUID"
              value={organizationId}
              required
              pattern="[0-9a-fA-F-]{36}"
              onChange={(event) => setOrganizationId(event.target.value)}
            />
            <Button disabled={busy} type="submit">
              Create invitation
            </Button>
          </form>
        </Card>
      ) : null}
      {participants?.length === 0 ? (
        <EmptyState
          title="No pilot participants"
          description="Invite an existing customer or operator organization."
        />
      ) : null}
      <div className="platform-review-list">
        {participants?.map((item) => (
          <Card as="article" className="platform-review-card" key={item.id}>
            <div>
              <h2>{item.organization_name}</h2>
              <Badge>{item.status}</Badge>
            </div>
            <p>
              {item.participant_type} · {item.organization_id}
            </p>
            {canManage ? (
              <div className="platform-actions">
                {item.status === "INVITED" || item.status === "SUSPENDED" ? (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      changeParticipant(item, "ACTIVE", "OWNER_APPROVED")
                    }
                  >
                    Activate
                  </Button>
                ) : null}
                {item.status === "ACTIVE" ? (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() =>
                      changeParticipant(
                        item,
                        "SUSPENDED",
                        "MANUAL_REVIEW_REQUIRED",
                      )
                    }
                  >
                    Suspend
                  </Button>
                ) : null}
                {item.status !== "REVOKED" ? (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() =>
                      changeParticipant(
                        item,
                        "REVOKED",
                        "ACCESS_NO_LONGER_REQUIRED",
                      )
                    }
                  >
                    Revoke
                  </Button>
                ) : null}
              </div>
            ) : null}
          </Card>
        ))}
      </div>
      <nav className="platform-pagination" aria-label="Pilot participant pages">
        <Button
          variant="secondary"
          disabled={offset === 0 || busy}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </Button>
        <span>
          Items {participants?.length ? offset + 1 : 0}–
          {offset + (participants?.length ?? 0)}
        </span>
        <Button
          variant="secondary"
          disabled={!participants || participants.length < PAGE_SIZE || busy}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </Button>
      </nav>
      <Card className="platform-audit">
        <h2>Recent governance audit</h2>
        {audits.length ? (
          <ol>
            {audits.map((item) => (
              <li key={item.id}>
                {item.action}: {item.previous_state} → {item.new_state}
                <span>
                  {item.reason} · {new Date(item.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p>No governance mutations recorded.</p>
        )}
      </Card>
    </Container>
  );
}
