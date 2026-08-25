import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortalTripRequestsPage from "@/app/portal/trip-requests/page";
import PortalTripRequestDetailPage from "@/app/portal/trip-requests/[id]/page";
import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";

const listTripRequests = vi.fn();
const getTripRequest = vi.fn();
const getAirport = vi.fn();

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequests: (...a: unknown[]) => listTripRequests(...a),
    getTripRequest: (...a: unknown[]) => getTripRequest(...a),
    getAirport: (...a: unknown[]) => getAirport(...a),
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
  orgContext = { activeOrganizationId: "org-1", hasCustomerContext: true };
  params = { id: TRIP.id };
  listTripRequests.mockReset();
  getTripRequest.mockReset();
  getAirport.mockReset();
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
  it("renders real trip fields and resolves airport labels, with no mutation controls", async () => {
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
    // Read-only: no create/submit/cancel/edit/book/pay controls.
    for (const name of [
      /submit/i,
      /cancel/i,
      /edit/i,
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
