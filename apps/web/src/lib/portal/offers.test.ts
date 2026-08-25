import { describe, expect, it } from "vitest";

import type { CustomerOffer } from "@/lib/api/types";
import {
  compareCustomerOffers,
  formatOfferMoney,
  offerAvailability,
} from "@/lib/portal/offers";

const offer = (
  id: string,
  currency: "EUR" | "GBP" | "USD",
  amount: number,
  status: CustomerOffer["status"] = "SUBMITTED",
): CustomerOffer => ({
  id,
  trip_request_id: "trip",
  status,
  currency,
  total_amount_minor: amount,
  tax_amount_minor: 100,
  valid_until: "2026-12-01T00:00:00Z",
  operator_legal_name: "Operator",
  aircraft_registration: "EI-ABC",
  aircraft_manufacturer: "Cessna",
  aircraft_model: "CJ3+",
  aircraft_category: "LIGHT_JET",
  included_services: null,
  excluded_services: null,
  cancellation_policy: null,
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:00Z",
  response_audience: "customer",
});

describe("offer presentation helpers", () => {
  it("formats integer minor units for supported currencies", () => {
    expect(formatOfferMoney(123456, "EUR")).toContain("1,234.56");
    expect(formatOfferMoney(123456, "GBP")).toContain("1,234.56");
    expect(formatOfferMoney(123456, "USD")).toContain("1,234.56");
  });
  it("groups by currency before comparing integer amounts", () => {
    const sorted = [
      offer("usd", "USD", 1),
      offer("eur2", "EUR", 200),
      offer("eur1", "EUR", 100),
    ].sort(compareCustomerOffers);
    expect(sorted.map((item) => item.id)).toEqual(["eur1", "eur2", "usd"]);
  });
  it("fails closed for unknown status", () => {
    expect(offerAvailability("SUBMITTED")).toBe("available");
    expect(offerAvailability("EXPIRED")).toBe("expired");
    expect(offerAvailability("SELECTED")).toBe("selected");
    expect(offerAvailability("FUTURE_STATE")).toBe("unavailable");
  });
});
