import { describe, expect, it } from "vitest";

import {
  bookingStatusLabel,
  canCreateBookingRequest,
} from "@/lib/portal/bookings";
import type { CustomerOffer } from "@/lib/api/types";

const selectedOffer: CustomerOffer = {
  id: "offer",
  trip_request_id: "trip",
  status: "SELECTED",
  currency: "EUR",
  total_amount_minor: 100,
  tax_amount_minor: 10,
  valid_until: "2099-01-01T00:00:00Z",
  operator_legal_name: "Operator",
  aircraft_registration: "EI-ONE",
  aircraft_manufacturer: "Maker",
  aircraft_model: "Model",
  aircraft_category: "LIGHT_JET",
  included_services: null,
  excluded_services: null,
  cancellation_policy: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  response_audience: "customer",
};

describe("customer Booking helpers", () => {
  it("allows only a live selected offer on a submitted trip", () => {
    expect(canCreateBookingRequest("SUBMITTED", selectedOffer, 0)).toBe(true);
    expect(canCreateBookingRequest("DRAFT", selectedOffer, 0)).toBe(false);
    expect(
      canCreateBookingRequest(
        "SUBMITTED",
        { ...selectedOffer, status: "SUBMITTED" },
        0,
      ),
    ).toBe(false);
    expect(
      canCreateBookingRequest(
        "SUBMITTED",
        { ...selectedOffer, valid_until: null },
        0,
      ),
    ).toBe(false);
    expect(
      canCreateBookingRequest(
        "SUBMITTED",
        { ...selectedOffer, valid_until: "not-a-date" },
        0,
      ),
    ).toBe(false);
    expect(
      canCreateBookingRequest(
        "SUBMITTED",
        { ...selectedOffer, status: "FUTURE" } as unknown as CustomerOffer,
        0,
      ),
    ).toBe(false);
    for (const status of ["CANCELLED", "EXPIRED", "FUTURE"])
      expect(canCreateBookingRequest(status, selectedOffer, 0)).toBe(false);
    expect(
      canCreateBookingRequest(
        "SUBMITTED",
        { ...selectedOffer, valid_until: "2020-01-01T00:00:00Z" },
        Date.parse("2021-01-01T00:00:00Z"),
      ),
    ).toBe(false);
  });

  it("uses factual labels and fails closed for unknown statuses", () => {
    expect(bookingStatusLabel("PENDING_OPERATOR_CONFIRMATION")).toBe(
      "Awaiting operator confirmation",
    );
    expect(bookingStatusLabel("CONFIRMED")).toBe("Confirmed by the operator");
    expect(bookingStatusLabel("REJECTED")).toBe(
      "The operator could not confirm this booking",
    );
    expect(bookingStatusLabel("CANCELLED")).toBe("This booking was cancelled");
    expect(bookingStatusLabel("FUTURE")).toBe("Booking status unavailable");
  });
});
