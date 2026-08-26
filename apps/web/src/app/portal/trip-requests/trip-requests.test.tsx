import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortalTripRequestsPage from "@/app/portal/trip-requests/page";
import PortalTripRequestDetailPage from "@/app/portal/trip-requests/[id]/page";
import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";

const listTripRequests = vi.fn();
const getTripRequest = vi.fn();
const getAirport = vi.fn();
const cancelTripRequest = vi.fn();
const listTripRequestOffers = vi.fn();
const selectOffer = vi.fn();
const getTripRequestBooking = vi.fn();

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequests: (...a: unknown[]) => listTripRequests(...a),
    getTripRequest: (...a: unknown[]) => getTripRequest(...a),
    getAirport: (...a: unknown[]) => getAirport(...a),
    cancelTripRequest: (...a: unknown[]) => cancelTripRequest(...a),
    listTripRequestOffers: (...a: unknown[]) => listTripRequestOffers(...a),
    selectOffer: (...a: unknown[]) => selectOffer(...a),
    getTripRequestBooking: (...a: unknown[]) => getTripRequestBooking(...a),
  },
}));

let orgContext = {
  activeOrganizationId: "org-1" as string | null,
  hasCustomerContext: true,
};
vi.mock("@/components/session/org-context", () => ({
  useActiveOrganization: () => orgContext,
}));

let params: { id: string } = { id: "b32413c8-88e9-4c05-89e5-78afb14f5eb4" };
vi.mock("next/navigation", () => ({
  useParams: () => params,
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const TRIP: CustomerTripRequest = {
  id: "b32413c8-88e9-4c05-89e5-78afb14f5eb4",
  status: "SUBMITTED",
  version: 1,
  legs: [
    {
      id: "leg-1",
      sequence: 1,
      origin_airport_id: "a1",
      destination_airport_id: "a2",
      departure_at: "2026-09-01T08:00:00Z",
      origin_timezone: "Europe/Dublin",
      destination_timezone: "Europe/London",
      passenger_count: 2,
    },
  ],
  passengers: [{ id: "p1", first_name: "Ada", last_name: "Byron" }],
  requirements: {
    baggage_notes: null,
    catering_notes: null,
    ground_transport_requested: false,
    special_assistance_notes: null,
    customer_notes: "Window seat please",
    pet_present: false,
  },
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:00Z",
};

beforeEach(() => {
  getTripRequestBooking.mockReset();
  getTripRequestBooking.mockRejectedValue(
    new ApiError(404, "not_found", "Not found", "client"),
  );
  orgContext = { activeOrganizationId: "org-1", hasCustomerContext: true };
  params = { id: TRIP.id };
  listTripRequests.mockReset();
  getTripRequest.mockReset();
  getAirport.mockReset();
  cancelTripRequest.mockReset();
  listTripRequestOffers.mockReset();
  selectOffer.mockReset();
  listTripRequestOffers.mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PortalTripRequestsPage (list)", () => {
  it("renders the customer's trip requests with status and a detail link", async () => {
    listTripRequests.mockResolvedValueOnce([TRIP]);
    render(<PortalTripRequestsPage />);
    expect(
      await screen.findByRole("heading", { name: "Trip requests" }),
    ).toBeTruthy();
    const link = await screen.findByRole("link", { name: /Request B32413C8/ });
    expect(link.getAttribute("href")).toBe(`/portal/trip-requests/${TRIP.id}`);
    expect(screen.getByText("SUBMITTED")).toBeTruthy();
    expect(screen.getByText(/1 leg/)).toBeTruthy();
  });

  it("shows an honest empty state when there are none", async () => {
    listTripRequests.mockResolvedValueOnce([]);
    render(<PortalTripRequestsPage />);
    expect(await screen.findByText("No trip requests yet")).toBeTruthy();
  });

  it("offers a New trip request CTA linking to the create page", async () => {
    listTripRequests.mockResolvedValueOnce([]);
    render(<PortalTripRequestsPage />);
    const cta = await screen.findByRole("link", { name: "New trip request" });
    expect(cta.getAttribute("href")).toBe("/portal/trip-requests/new");
  });

  it("hides the New trip request CTA without a customer context", async () => {
    orgContext = { activeOrganizationId: null, hasCustomerContext: false };
    listTripRequests.mockResolvedValue([]);
    render(<PortalTripRequestsPage />);
    await screen.findByText("No active customer account");
    expect(screen.queryByRole("link", { name: "New trip request" })).toBeNull();
  });

  it("shows a forbidden error distinctly from a generic error", async () => {
    listTripRequests.mockRejectedValueOnce(
      new ApiError(403, "forbidden", "x", "forbidden"),
    );
    render(<PortalTripRequestsPage />);
    expect(
      await screen.findByText("You don’t have access to these trip requests."),
    ).toBeTruthy();
  });

  it("prompts to link a customer account when there is no customer context", async () => {
    orgContext = { activeOrganizationId: null, hasCustomerContext: false };
    listTripRequests.mockResolvedValue([]);
    render(<PortalTripRequestsPage />);
    expect(await screen.findByText("No active customer account")).toBeTruthy();
    // The no-context alert is shown regardless of any read outcome; no list renders.
    expect(screen.queryByText(/Request /)).toBeNull();
  });
});

describe("PortalTripRequestDetailPage", () => {
  it("integrates selection into a SUBMITTED trip and forwards active organization context", async () => {
    getTripRequest.mockResolvedValueOnce(TRIP);
    getAirport.mockRejectedValue(new ApiError(404, "not_found", "x", "client"));
    const offer = {
      id: "11111111-2222-4333-8444-555555555555",
      trip_request_id: TRIP.id,
      status: "SUBMITTED" as const,
      currency: "EUR" as const,
      total_amount_minor: 10000,
      tax_amount_minor: 1000,
      valid_until: "2099-01-01T00:00:00Z",
      operator_legal_name: "Factual Air Limited",
      aircraft_registration: "EI-REAL",
      aircraft_manufacturer: "Cessna",
      aircraft_model: "Citation",
      aircraft_category: "LIGHT_JET",
      included_services: null,
      excluded_services: null,
      cancellation_policy: null,
      created_at: "2026-08-25T00:00:00Z",
      updated_at: "2026-08-25T00:00:00Z",
      response_audience: "customer" as const,
    };
    listTripRequestOffers.mockResolvedValueOnce([offer]);
    selectOffer.mockResolvedValueOnce({ ...offer, status: "SELECTED" });
    render(<PortalTripRequestDetailPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Select offer" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Select this offer" }));
    await waitFor(() =>
      expect(selectOffer).toHaveBeenCalledWith(TRIP.id, offer.id, "org-1"),
    );
    expect(await screen.findByText("Selected")).toBeTruthy();
    expect(screen.getByText("SUBMITTED")).toBeTruthy();
  });
  it("keeps the trip detail rendered when the isolated offers read fails", async () => {
    getTripRequest.mockResolvedValueOnce(TRIP);
    getAirport.mockRejectedValue(new ApiError(404, "not_found", "x", "client"));
    listTripRequestOffers.mockRejectedValueOnce(
      new ApiError(500, "internal", "raw backend body", "server"),
    );
    render(<PortalTripRequestDetailPage />);
    expect(
      await screen.findByRole("heading", { name: "Request B32413C8" }),
    ).toBeTruthy();
    expect(await screen.findByText("Offers couldn’t be loaded")).toBeTruthy();
    expect(screen.getByText("SUBMITTED")).toBeTruthy();
    expect(screen.queryByText("raw backend body")).toBeNull();
  });

  it("renders real trip fields and resolves airport labels, with only a Cancel action", async () => {
    getTripRequest.mockResolvedValueOnce(TRIP);
    getAirport.mockImplementation((id: string) =>
      Promise.resolve(
        id === "a1"
          ? {
              id: "a1",
              icao_code: "EIDW",
              iata_code: "DUB",
              name: "Dublin",
              city: "Dublin",
              country_code: "IE",
            }
          : {
              id: "a2",
              icao_code: "EGLL",
              iata_code: "LHR",
              name: "Heathrow",
              city: "London",
              country_code: "GB",
            },
      ),
    );
    render(<PortalTripRequestDetailPage />);
    expect(
      await screen.findByRole("heading", { name: "Request B32413C8" }),
    ).toBeTruthy();
    expect(screen.getByText("SUBMITTED")).toBeTruthy();
    expect(screen.getByText(/Dublin \(DUB\)/)).toBeTruthy();
    expect(screen.getByText(/London \(LHR\)/)).toBeTruthy();
    expect(screen.getByText("Ada Byron")).toBeTruthy();
    expect(screen.getByText("Window seat please")).toBeTruthy();
    // A SUBMITTED request is cancellable → the Cancel action is present…
    expect(screen.getByRole("button", { name: "Cancel request" })).toBeTruthy();
    // …but no other mutation controls (no submit/edit/withdraw/book/pay/select).
    for (const name of [
      /submit/i,
      /edit/i,
      /withdraw/i,
      /book/i,
      /pay/i,
      /select/i,
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(getTripRequest).toHaveBeenCalledWith(
      TRIP.id,
      "org-1",
      expect.anything(),
    );
  });

  it("hides the Cancel action for a non-cancellable status", async () => {
    getTripRequest.mockResolvedValueOnce({ ...TRIP, status: "CANCELLED" });
    getAirport.mockResolvedValue({
      id: "a1",
      icao_code: "EIDW",
      iata_code: "DUB",
      name: "Dublin",
      city: "Dublin",
      country_code: "IE",
    });
    render(<PortalTripRequestDetailPage />);
    await screen.findByRole("heading", { name: "Request B32413C8" });
    expect(screen.getByText("CANCELLED")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel request" })).toBeNull();
  });

  it("cancels via confirmation and reflects CANCELLED, hiding the Cancel action", async () => {
    getTripRequest.mockResolvedValueOnce(TRIP);
    getAirport.mockResolvedValue({
      id: "a1",
      icao_code: "EIDW",
      iata_code: "DUB",
      name: "Dublin",
      city: "Dublin",
      country_code: "IE",
    });
    cancelTripRequest.mockResolvedValueOnce({
      ...TRIP,
      status: "CANCELLED",
      version: 2,
    });
    render(<PortalTripRequestDetailPage />);
    await screen.findByRole("heading", { name: "Request B32413C8" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    // Explicit confirmation, then confirm (the destructive button).
    expect(screen.getByText("Cancel this trip request?")).toBeTruthy();
    fireEvent.click(
      screen.getAllByRole("button", { name: /Cancel request/ }).pop()!,
    );
    // Uses the current id + version.
    await waitFor(() =>
      expect(cancelTripRequest).toHaveBeenCalledWith(TRIP.id, 1, "org-1"),
    );
    // The displayed request becomes CANCELLED and the Cancel action disappears.
    expect(await screen.findByText("Request cancelled")).toBeTruthy();
    expect(screen.getByText("CANCELLED")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel request" })).toBeNull();
  });

  it("on a cancel conflict, refresh re-reads the request", async () => {
    getTripRequest
      .mockResolvedValueOnce(TRIP)
      .mockResolvedValueOnce({ ...TRIP, status: "CANCELLED", version: 5 });
    getAirport.mockResolvedValue({
      id: "a1",
      icao_code: "EIDW",
      iata_code: "DUB",
      name: "Dublin",
      city: "Dublin",
      country_code: "IE",
    });
    cancelTripRequest.mockRejectedValueOnce(
      new ApiError(409, "conflict", "raw", "conflict"),
    );
    render(<PortalTripRequestDetailPage />);
    await screen.findByRole("heading", { name: "Request B32413C8" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    fireEvent.click(
      screen.getAllByRole("button", { name: /Cancel request/ }).pop()!,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Refresh request" }),
    );
    // A second real GET happens and shows the current status.
    await waitFor(() => expect(getTripRequest).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("CANCELLED")).toBeTruthy();
  });

  it("shows a not-found message on 404 without leaking internals", async () => {
    getTripRequest.mockRejectedValueOnce(
      new ApiError(404, "not_found", "x", "client"),
    );
    render(<PortalTripRequestDetailPage />);
    expect(await screen.findByText("Trip request not found")).toBeTruthy();
    expect(screen.queryByText(/not_found/)).toBeNull();
  });

  it("still renders legs when an airport lookup fails (timezone fallback)", async () => {
    getTripRequest.mockResolvedValueOnce(TRIP);
    getAirport.mockRejectedValue(new ApiError(404, "not_found", "x", "client"));
    render(<PortalTripRequestDetailPage />);
    expect(
      await screen.findByRole("heading", { name: "Request B32413C8" }),
    ).toBeTruthy();
    expect(screen.getByText(/Europe\/Dublin/)).toBeTruthy();
    expect(screen.getByText(/Europe\/London/)).toBeTruthy();
  });
});
