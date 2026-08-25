import type { Airport, CustomerTripRequest, TripLeg } from "@/lib/api/types";

/**
 * Presentation helpers for the customer trip-request read surfaces (Phase 9.3.A). These are
 * pure formatting/derivation functions over the customer-safe read models — no network, no
 * state, no mutation. They exist so the list and detail pages render consistent, honest
 * labels for real backend data (status, dates, legs) without inventing fields.
 */

type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

/**
 * Map a real `TripRequestStatus` to a badge tone. Unknown/future statuses fall back to
 * neutral rather than guessing, so a new backend status never renders a misleading colour.
 */
export function tripStatusTone(status: string): BadgeTone {
  switch (status) {
    case "BOOKED":
      return "success";
    case "CANCELLED":
      return "danger";
    case "EXPIRED":
      return "warning";
    case "SUBMITTED":
    case "QUOTING":
    case "QUOTES_AVAILABLE":
    case "QUOTE_SELECTED":
      return "info";
    case "DRAFT":
    default:
      return "neutral";
  }
}

/** A short, human-readable handle derived from the real UUID (never a fabricated code). */
export function tripHandle(id: string): string {
  return `Request ${id.slice(0, 8).toUpperCase()}`;
}

/** Format an ISO timestamp as a readable date-time, or an em dash when absent/invalid. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Total passengers across the trip's own passenger roster (attached to the request). */
export function passengerCount(trip: CustomerTripRequest): number {
  return trip.passengers.length;
}

/** A concise one-line summary of a trip's legs for the list row. */
export function legSummary(trip: CustomerTripRequest): string {
  const count = trip.legs.length;
  const legWord = count === 1 ? "leg" : "legs";
  const first = firstDeparture(trip.legs);
  const departs = first ? ` · departs ${formatDateTime(first)}` : "";
  return `${count} ${legWord}${departs}`;
}

/** The earliest scheduled departure across legs (by sequence), if any. */
export function firstDeparture(legs: readonly TripLeg[]): string | null {
  const ordered = [...legs].sort((a, b) => a.sequence - b.sequence);
  return ordered[0]?.departure_at ?? null;
}

/**
 * A readable airport label from a resolved {@link Airport}, falling back to a leg's IANA
 * timezone (which encodes a region) and finally to nothing, so a leg is never blank even if
 * the public airport lookup is unavailable.
 */
export function airportLabel(
  airport: Airport | undefined,
  fallbackTimezone: string,
): string {
  if (airport) {
    const code = airport.iata_code ?? airport.icao_code;
    return `${airport.city} (${code})`;
  }
  return fallbackTimezone;
}
