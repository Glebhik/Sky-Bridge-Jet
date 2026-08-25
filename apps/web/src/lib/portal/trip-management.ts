import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";

/**
 * Framework-free core for Phase 9.3.C trip management + dashboard: cancel eligibility, safe
 * cancel error mapping, and client-side aggregation over the customer's real trip requests.
 * These mirror the audited backend semantics exactly and are directly unit-testable.
 */

/**
 * Statuses from which the backend allows a customer cancel, per `_ALLOWED_TRIP_TRANSITIONS`
 * (DRAFT → CANCELLED, SUBMITTED → CANCELLED; every other status has no CANCELLED transition
 * and returns 409). The UI shows Cancel ONLY for these; the backend remains authoritative
 * even when the UI hides the action.
 */
export const CANCELLABLE_STATUSES: ReadonlySet<string> = new Set([
  "DRAFT",
  "SUBMITTED",
]);

/** True when a trip request in `status` can be cancelled by the customer (backend-authoritative). */
export function canCancelTripRequest(status: string): boolean {
  return CANCELLABLE_STATUSES.has(status);
}

/**
 * Active is an explicit fail-closed classification: DRAFT, SUBMITTED, QUOTING,
 * QUOTES_AVAILABLE, and QUOTE_SELECTED. BOOKED, CANCELLED, EXPIRED, and every unknown/future
 * status are not active until deliberately classified.
 */
export const ACTIVE_STATUSES: ReadonlySet<string> = new Set([
  "DRAFT",
  "SUBMITTED",
  "QUOTING",
  "QUOTES_AVAILABLE",
  "QUOTE_SELECTED",
]);

/**
 * An "active" request is one still progressing — i.e. not terminal. With the current enum
 * that is DRAFT, SUBMITTED, QUOTING, QUOTES_AVAILABLE, QUOTE_SELECTED. Defined explicitly so
 * a future status is classified deliberately, never by accident.
 */
export function isActiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

/** Factual dashboard counts computed from the customer's own real trip requests. */
export interface TripRequestSummary {
  readonly total: number;
  readonly active: number;
  readonly submitted: number;
  readonly cancelled: number;
}

/** Aggregate real trip requests into factual counts (no invented commercial metrics). */
export function summarizeTripRequests(
  trips: readonly CustomerTripRequest[],
): TripRequestSummary {
  let active = 0;
  let submitted = 0;
  let cancelled = 0;
  for (const trip of trips) {
    if (isActiveStatus(trip.status)) active += 1;
    if (trip.status === "SUBMITTED") submitted += 1;
    if (trip.status === "CANCELLED") cancelled += 1;
  }
  return { total: trips.length, active, submitted, cancelled };
}

/**
 * The customer's most recent requests, newest first. Sorting is deterministic: by
 * `created_at` descending, with the id as a stable tiebreaker so equal timestamps never
 * reorder between renders.
 */
export function recentTripRequests(
  trips: readonly CustomerTripRequest[],
  limit = 5,
): readonly CustomerTripRequest[] {
  return [...trips]
    .sort((a, b) => {
      if (a.created_at !== b.created_at)
        return a.created_at < b.created_at ? 1 : -1;
      return a.id < b.id ? 1 : -1;
    })
    .slice(0, limit);
}

// ── Safe cancel error messages ─────────────────────────────────────────────────────────────
// Never surface the raw backend message/code/body. Map only the statuses this flow can see.

/** True for a version/state conflict (409) — the caller should offer a refresh, not a retry. */
export function isCancelConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

export function messageForCancelError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return "This request changed before it could be cancelled. Refresh to see its current status.";
    }
    if (error.status === 404) {
      return "This request is no longer available.";
    }
  }
  return "We couldn't cancel your request. Please try again.";
}
