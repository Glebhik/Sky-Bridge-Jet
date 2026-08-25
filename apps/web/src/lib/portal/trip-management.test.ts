import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";
import {
  canCancelTripRequest,
  isActiveStatus,
  isCancelConflict,
  messageForCancelError,
  recentTripRequests,
  summarizeTripRequests,
} from "@/lib/portal/trip-management";

// Every TripRequestStatus value currently defined in the backend enum.
const ALL_STATUSES = [
  "DRAFT",
  "SUBMITTED",
  "QUOTING",
  "QUOTES_AVAILABLE",
  "QUOTE_SELECTED",
  "BOOKED",
  "CANCELLED",
  "EXPIRED",
] as const;

function trip(
  id: string,
  status: string,
  createdAt: string,
): CustomerTripRequest {
  return {
    id,
    status,
    version: 1,
    legs: [],
    passengers: [],
    requirements: {
      baggage_notes: null,
      catering_notes: null,
      ground_transport_requested: false,
      special_assistance_notes: null,
      customer_notes: null,
      pet_present: false,
    },
    created_at: createdAt,
    updated_at: createdAt,
  };
}

describe("canCancelTripRequest — mirrors backend transitions exactly", () => {
  it("allows cancel only from DRAFT and SUBMITTED", () => {
    const allowed = ALL_STATUSES.filter((s) => canCancelTripRequest(s));
    expect(allowed).toEqual(["DRAFT", "SUBMITTED"]);
  });

  it("disallows cancel for every other status (incl. already CANCELLED)", () => {
    for (const s of [
      "QUOTING",
      "QUOTES_AVAILABLE",
      "QUOTE_SELECTED",
      "BOOKED",
      "CANCELLED",
      "EXPIRED",
    ]) {
      expect(canCancelTripRequest(s)).toBe(false);
    }
    // An unknown/future status is not cancellable by default.
    expect(canCancelTripRequest("SOMETHING_NEW")).toBe(false);
  });
});

describe("isActiveStatus — non-terminal classification", () => {
  it("treats DRAFT/SUBMITTED/QUOTING/QUOTES_AVAILABLE/QUOTE_SELECTED as active", () => {
    for (const s of [
      "DRAFT",
      "SUBMITTED",
      "QUOTING",
      "QUOTES_AVAILABLE",
      "QUOTE_SELECTED",
    ]) {
      expect(isActiveStatus(s)).toBe(true);
    }
  });

  it("treats BOOKED/CANCELLED/EXPIRED as terminal (not active)", () => {
    for (const s of ["BOOKED", "CANCELLED", "EXPIRED"]) {
      expect(isActiveStatus(s)).toBe(false);
    }
    // Future statuses must be classified deliberately, never counted as active by default.
    expect(isActiveStatus("SOMETHING_NEW")).toBe(false);
  });
});

describe("summarizeTripRequests — factual counts", () => {
  it("computes total/active/submitted/cancelled exactly", () => {
    const trips = [
      trip("a", "DRAFT", "2026-01-01T00:00:00Z"),
      trip("b", "SUBMITTED", "2026-01-02T00:00:00Z"),
      trip("c", "SUBMITTED", "2026-01-03T00:00:00Z"),
      trip("d", "CANCELLED", "2026-01-04T00:00:00Z"),
      trip("e", "BOOKED", "2026-01-05T00:00:00Z"),
      trip("f", "EXPIRED", "2026-01-06T00:00:00Z"),
    ];
    expect(summarizeTripRequests(trips)).toEqual({
      total: 6,
      active: 3, // DRAFT + 2 SUBMITTED
      submitted: 2,
      cancelled: 1,
    });
  });

  it("is all-zero for an empty list", () => {
    expect(summarizeTripRequests([])).toEqual({
      total: 0,
      active: 0,
      submitted: 0,
      cancelled: 0,
    });
  });
});

describe("recentTripRequests — deterministic newest-first", () => {
  it("sorts by created_at desc, tiebreaks by id, and applies the limit", () => {
    const trips = [
      trip("a", "DRAFT", "2026-01-01T00:00:00Z"),
      trip("z", "DRAFT", "2026-01-03T00:00:00Z"),
      trip("m", "DRAFT", "2026-01-03T00:00:00Z"), // same ts as z → id tiebreak
      trip("b", "DRAFT", "2026-01-02T00:00:00Z"),
    ];
    const recent = recentTripRequests(trips, 3).map((t) => t.id);
    // Newest ts first; for the tie at 2026-01-03, larger id ("z") comes before "m".
    expect(recent).toEqual(["z", "m", "b"]);
  });

  it("does not mutate the input array", () => {
    const trips = [
      trip("a", "DRAFT", "2026-01-01T00:00:00Z"),
      trip("b", "DRAFT", "2026-01-02T00:00:00Z"),
    ];
    const before = trips.map((t) => t.id);
    recentTripRequests(trips);
    expect(trips.map((t) => t.id)).toEqual(before);
  });
});

describe("cancel error mapping — safe, status-specific", () => {
  it("flags 409 as a conflict and uses a refresh message", () => {
    const err = new ApiError(409, "conflict", "raw", "conflict");
    expect(isCancelConflict(err)).toBe(true);
    expect(messageForCancelError(err)).toMatch(/changed before it could be/i);
  });

  it("uses an unavailable message on 404 and a generic one otherwise", () => {
    expect(
      messageForCancelError(new ApiError(404, "not_found", "raw", "client")),
    ).toMatch(/no longer available/i);
    const server = new ApiError(500, "server", "RAW-SECRET", "server");
    expect(isCancelConflict(server)).toBe(false);
    expect(messageForCancelError(server)).not.toContain("RAW-SECRET");
  });
});
