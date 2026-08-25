"use client";

import { useRef, useState } from "react";

import { portalApi } from "@/lib/api/client";
import type { CustomerTripRequest } from "@/lib/api/types";
import {
  isCancelConflict,
  messageForCancelError,
} from "@/lib/portal/trip-management";
import { Alert, Button } from "@/components/ui/primitives";

/**
 * The eligibility-aware cancel action for a customer's own trip request (Phase 9.3.C). The
 * parent renders this ONLY for cancellable statuses; this component owns the explicit
 * confirmation step, the single cancel mutation, and the safe conflict/error handling.
 *
 * Cancellation is a real side effect, so it requires an explicit two-step confirmation, a
 * synchronous in-flight guard (one confirm can never fire two POSTs), and it never optimistically
 * marks the request CANCELLED — the displayed request is only updated from the real response.
 */
export interface TripCancelPanelProps {
  readonly trip: CustomerTripRequest;
  readonly organizationId?: string;
  /** Called with the real CANCELLED trip returned by the backend. */
  readonly onCancelled: (updated: CustomerTripRequest) => void;
  /** Called when a 409 means the caller should re-read the request from the backend. */
  readonly onRefreshNeeded: () => void;
}

type Mode = "idle" | "confirming" | "cancelling" | "conflict" | "error";

export function TripCancelPanel({
  trip,
  organizationId,
  onCancelled,
  onRefreshNeeded,
}: TripCancelPanelProps) {
  const [mode, setMode] = useState<Mode>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  const busy = mode === "cancelling";

  async function doCancel(): Promise<void> {
    if (inFlightRef.current) return; // synchronous double-confirm guard
    inFlightRef.current = true;
    setMode("cancelling");
    setErrorMessage(null);
    try {
      // expected_version is the version the request was last read at — never fabricated.
      const updated = await portalApi.cancelTripRequest(
        trip.id,
        trip.version,
        organizationId,
      );
      onCancelled(updated); // real CANCELLED response; parent hides this panel
    } catch (error) {
      if (isCancelConflict(error)) {
        setMode("conflict");
      } else {
        setErrorMessage(messageForCancelError(error));
        setMode("error");
      }
    } finally {
      inFlightRef.current = false;
    }
  }

  if (mode === "conflict") {
    return (
      <Alert tone="warning" title="Request changed">
        This request changed before it could be cancelled. Refresh to see its
        current status.
        <div className="cancel-panel__actions">
          <Button variant="secondary" type="button" onClick={onRefreshNeeded}>
            Refresh request
          </Button>
        </div>
      </Alert>
    );
  }

  if (mode === "confirming" || mode === "cancelling" || mode === "error") {
    return (
      <div className="cancel-panel" role="group" aria-label="Cancel request">
        {mode === "error" && errorMessage ? (
          <Alert tone="error" title="We couldn’t cancel your request">
            {errorMessage}
          </Alert>
        ) : null}
        <p className="cancel-panel__prompt">Cancel this trip request?</p>
        <p className="cancel-panel__detail">
          This will stop the current request. This action cannot be undone from
          the customer portal.
        </p>
        <div className="cancel-panel__actions">
          <Button
            variant="ghost"
            type="button"
            onClick={() => {
              setMode("idle");
              setErrorMessage(null);
            }}
            disabled={busy}
          >
            Keep request
          </Button>
          <Button
            variant="secondary"
            className="button--danger"
            type="button"
            onClick={doCancel}
            disabled={busy}
            aria-busy={busy}
          >
            {busy ? "Cancelling…" : "Cancel request"}
          </Button>
        </div>
      </div>
    );
  }

  // idle
  return (
    <Button
      variant="secondary"
      className="button--danger"
      type="button"
      onClick={() => setMode("confirming")}
    >
      Cancel request
    </Button>
  );
}
