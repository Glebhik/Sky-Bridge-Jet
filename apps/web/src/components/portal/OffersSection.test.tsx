import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OffersSection } from "@/components/portal/OffersSection";
import type { CustomerOffer } from "@/lib/api/types";

const listTripRequestOffers = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequestOffers: (...args: unknown[]) =>
      listTripRequestOffers(...args),
  },
}));

const makeOffer = (
  status: CustomerOffer["status"],
  currency: CustomerOffer["currency"] = "EUR",
): CustomerOffer => ({
  id: `${status}-${currency}`,
  trip_request_id: "trip",
  status,
  currency,
  total_amount_minor: 123456,
  tax_amount_minor: 1000,
  valid_until: "2026-12-01T00:00:00Z",
  operator_legal_name:
    "A very long factual operator legal name Aviation Limited",
  aircraft_registration: "EI-LONG",
  aircraft_manufacturer: "Bombardier",
  aircraft_model: "Global 7500",
  aircraft_category: "ULTRA_LONG_RANGE",
  included_services: "Catering;Ground transfer",
  excluded_services: "De-icing",
  cancellation_policy:
    "A long factual cancellation policy that must wrap safely without creating an action.",
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:00Z",
  response_audience: "customer",
});

beforeEach(() => listTripRequestOffers.mockReset());

describe("OffersSection", () => {
  it("shows loading then an honest empty state", async () => {
    listTripRequestOffers.mockResolvedValueOnce([]);
    render(<OffersSection tripRequestId="trip" organizationId="org" />);
    expect(screen.getByText("Loading published offers…")).toBeTruthy();
    expect(
      await screen.findByText(
        "No published offers are available for this trip request.",
      ),
    ).toBeTruthy();
  });
  it("renders one factual offer without selection, booking, payment, or ranking claims", async () => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(<OffersSection tripRequestId="trip" organizationId="org" />);
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("€1,234.56")).toBeTruthy();
    expect(screen.getByText("EUR")).toBeTruthy();
    expect(
      screen.getByText(
        "A very long factual operator legal name Aviation Limited",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/Bombardier Global 7500.*ULTRA_LONG_RANGE.*EI-LONG/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /select|book|pay/i }),
    ).toBeNull();
    expect(screen.queryByRole("link", { name: /select|book|pay/i })).toBeNull();
    expect(screen.queryByText(/recommend|best|cheapest|saving/i)).toBeNull();
  });
  it("renders submitted, expired, selected and mixed currencies without actions or fake fields", async () => {
    listTripRequestOffers.mockResolvedValueOnce([
      makeOffer("SELECTED", "USD"),
      makeOffer("EXPIRED", "GBP"),
      makeOffer("SUBMITTED"),
    ]);
    render(<OffersSection tripRequestId="trip" organizationId="org" />);
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
    expect(screen.getByText("Selected")).toBeTruthy();
    expect(screen.getAllByText(/A very long factual/)).toHaveLength(3);
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.queryByText(/recommended|capacity|cabin|booking|payment/i),
    ).toBeNull();
  });
  it("isolates offer errors inside the section", async () => {
    listTripRequestOffers.mockRejectedValueOnce(
      new Error("raw backend secret"),
    );
    render(<OffersSection tripRequestId="trip" />);
    expect(await screen.findByText("Offers couldn’t be loaded")).toBeTruthy();
    expect(screen.queryByText("raw backend secret")).toBeNull();
  });
});
