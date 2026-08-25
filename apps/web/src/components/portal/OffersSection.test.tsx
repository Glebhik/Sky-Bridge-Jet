import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OffersSection } from "@/components/portal/OffersSection";
import type { CustomerOffer } from "@/lib/api/types";

const listTripRequestOffers = vi.fn();
const selectOffer = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequestOffers: (...args: unknown[]) =>
      listTripRequestOffers(...args),
    selectOffer: (...args: unknown[]) => selectOffer(...args),
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
  valid_until: "2099-12-01T00:00:00Z",
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

beforeEach(() => {
  listTripRequestOffers.mockReset();
  selectOffer.mockReset();
});

describe("OffersSection", () => {
  it("shows loading then an honest empty state", async () => {
    listTripRequestOffers.mockResolvedValueOnce([]);
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    expect(screen.getByText("Loading published offers…")).toBeTruthy();
    expect(
      await screen.findByText(
        "No published offers are available for this trip request.",
      ),
    ).toBeTruthy();
  });
  it("renders one factual offer with selection but no booking, payment, or ranking claims", async () => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
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
    expect(screen.getByRole("button", { name: "Select offer" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /book|pay/i })).toBeNull();
    expect(screen.queryByText(/recommend|best|cheapest|saving/i)).toBeNull();
  });
  it("renders submitted, expired, selected and mixed currencies without actions or fake fields", async () => {
    listTripRequestOffers.mockResolvedValueOnce([
      makeOffer("SELECTED", "USD"),
      makeOffer("EXPIRED", "GBP"),
      makeOffer("SUBMITTED"),
    ]);
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
    expect(screen.getByText("Selected")).toBeTruthy();
    expect(screen.getAllByText(/A very long factual/)).toHaveLength(3);
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /select/i })).toBeNull();
    expect(
      screen.queryByText(/recommended|capacity|cabin|booking|payment/i),
    ).toBeNull();
  });
  it("isolates offer errors inside the section", async () => {
    listTripRequestOffers.mockRejectedValueOnce(
      new Error("raw backend secret"),
    );
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(await screen.findByText("Offers couldn’t be loaded")).toBeTruthy();
    expect(screen.queryByText("raw backend secret")).toBeNull();
  });

  it("requires confirmation, submits once under double click, and locks on authoritative success", async () => {
    const offer = makeOffer("SUBMITTED");
    listTripRequestOffers.mockResolvedValueOnce([offer]);
    let resolveSelection!: (offer: CustomerOffer) => void;
    selectOffer.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSelection = resolve;
      }),
    );
    render(
      <OffersSection
        tripRequestId="trip"
        tripStatus="SUBMITTED"
        organizationId="org"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    expect(screen.getByText(/does not create a booking/)).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Select this offer" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(selectOffer).toHaveBeenCalledTimes(1);
    expect(selectOffer).toHaveBeenCalledWith("trip", offer.id, "org");
    expect(
      screen.getByRole("button", { name: "Keep comparing" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Selecting…" })).toBeDisabled();
    expect(
      screen
        .getByRole("heading", { name: "Confirm offer selection" })
        .closest("section"),
    ).toHaveAttribute("aria-busy", "true");
    resolveSelection({ ...offer, status: "SELECTED" });
    expect(await screen.findByText("Selected")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /select/i })).toBeNull();
  });

  it("handles a 409 without retry and refreshes only on explicit request", async () => {
    const { ApiError } = await import("@/lib/api/errors");
    listTripRequestOffers
      .mockResolvedValueOnce([makeOffer("SUBMITTED")])
      .mockResolvedValueOnce([makeOffer("SELECTED")]);
    selectOffer.mockRejectedValueOnce(
      new ApiError(409, "conflict", "raw secret", "conflict"),
    );
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Select this offer" }));
    expect(await screen.findByText("Offer selection changed")).toBeTruthy();
    expect(screen.queryByText("raw secret")).toBeNull();
    expect(selectOffer).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh offers" }));
    await waitFor(() => expect(listTripRequestOffers).toHaveBeenCalledTimes(2));
  });

  it("keeps comparing without calling the selection API", async () => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep comparing" }));
    expect(selectOffer).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("heading", { name: "Confirm offer selection" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Select offer" })).toBeTruthy();
  });

  it.each([
    "DRAFT",
    "QUOTING",
    "QUOTES_AVAILABLE",
    "QUOTE_SELECTED",
    "BOOKED",
    "CANCELLED",
    "EXPIRED",
    "FUTURE_TRIP_STATE",
  ])("fails closed for trip status %s", async (tripStatus) => {
    listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
    render(<OffersSection tripRequestId="trip" tripStatus={tripStatus} />);
    expect(await screen.findByText("Available")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Select offer" })).toBeNull();
  });

  it("fails closed for an unknown future offer status", async () => {
    const futureOffer = {
      ...makeOffer("SUBMITTED"),
      status: "FUTURE_OFFER_STATE",
    } as unknown as CustomerOffer;
    listTripRequestOffers.mockResolvedValueOnce([futureOffer]);
    render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Select offer" })).toBeNull();
  });

  it.each([
    [403, "forbidden"],
    [404, "client"],
    [0, "network"],
    [503, "server"],
  ] as const)(
    "keeps the known offer and hides raw selection error details for status %s",
    async (status, kind) => {
      const { ApiError } = await import("@/lib/api/errors");
      listTripRequestOffers.mockResolvedValueOnce([makeOffer("SUBMITTED")]);
      selectOffer.mockRejectedValueOnce(
        new ApiError(status, "raw_internal_code", "raw backend secret", kind),
      );
      render(<OffersSection tripRequestId="trip" tripStatus="SUBMITTED" />);
      fireEvent.click(
        await screen.findByRole("button", { name: "Select offer" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Select this offer" }),
      );
      expect(
        await screen.findByText("Offer couldn’t be selected"),
      ).toBeTruthy();
      expect(screen.getByText("Available")).toBeTruthy();
      expect(screen.queryByText("Selected")).toBeNull();
      expect(
        screen.queryByText(/raw backend secret|raw_internal_code/),
      ).toBeNull();
      expect(selectOffer).toHaveBeenCalledTimes(1);
    },
  );
});
