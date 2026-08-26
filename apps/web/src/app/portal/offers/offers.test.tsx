import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalOffersPage, {
  compareOffersLandingTrips,
} from "@/app/portal/offers/page";
import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";

const listTripRequests = vi.fn();
const listTripRequestOffers = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequests: (...args: unknown[]) => listTripRequests(...args),
    listTripRequestOffers: (...args: unknown[]) =>
      listTripRequestOffers(...args),
  },
}));

let orgContext = {
  activeOrganizationId: "org-1" as string | null,
  hasCustomerContext: true,
};
vi.mock("@/components/session/org-context", () => ({
  useActiveOrganization: () => orgContext,
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const trip = (
  id: string,
  createdAt: string,
  status = "SUBMITTED",
): CustomerTripRequest => ({
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
});

beforeEach(() => {
  orgContext = { activeOrganizationId: "org-1", hasCustomerContext: true };
  listTripRequests.mockReset();
  listTripRequestOffers.mockReset();
});

describe("PortalOffersPage", () => {
  it("shows loading then an honest empty state with a create CTA", async () => {
    listTripRequests.mockResolvedValueOnce([]);
    render(<PortalOffersPage />);
    expect(screen.getByText("Loading your trip requests…")).toBeTruthy();
    expect(
      await screen.findByText("You don’t have any trip requests yet."),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "New trip request" }),
    ).toHaveAttribute("href", "/portal/trip-requests/new");
  });

  it("fails safely without customer context", async () => {
    orgContext = { activeOrganizationId: null, hasCustomerContext: false };
    listTripRequests.mockResolvedValueOnce([]);
    render(<PortalOffersPage />);
    expect(await screen.findByText("No active customer account")).toBeTruthy();
  });

  it("shows a generic error without backend detail", async () => {
    listTripRequests.mockRejectedValueOnce(
      new ApiError(500, "internal_secret", "raw backend detail", "server"),
    );
    render(<PortalOffersPage />);
    expect(
      await screen.findByText("We couldn’t load your trip requests"),
    ).toBeTruthy();
    expect(screen.queryByText(/raw backend detail|internal_secret/)).toBeNull();
  });

  it("renders real statuses in deterministic order and correct detail links", async () => {
    const older = trip(
      "11111111-1111-4111-8111-111111111111",
      "2026-08-24T00:00:00Z",
      "DRAFT",
    );
    const newerLow = trip(
      "22222222-2222-4222-8222-222222222222",
      "2026-08-25T00:00:00Z",
    );
    const newerHigh = trip(
      "33333333-3333-4333-8333-333333333333",
      "2026-08-25T00:00:00Z",
      "CANCELLED",
    );
    listTripRequests.mockResolvedValueOnce([older, newerLow, newerHigh]);
    render(<PortalOffersPage />);
    const links = await screen.findAllByRole("link", { name: /Request / });
    expect(links.map((link) => link.textContent)).toEqual([
      "Request 33333333",
      "Request 22222222",
      "Request 11111111",
    ]);
    expect(screen.getByText("DRAFT")).toBeTruthy();
    expect(screen.getByText("CANCELLED")).toBeTruthy();
    expect(links[0]).toHaveAttribute(
      "href",
      `/portal/trip-requests/${newerHigh.id}`,
    );
    expect(listTripRequests).toHaveBeenCalledWith("org-1", expect.anything());
    expect(listTripRequestOffers).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/price|operator|aircraft|offers waiting/i),
    ).toBeNull();
  });

  it("uses id descending as the stable created-at tie-breaker", () => {
    const a = trip("aaaaaaaa", "2026-08-25T00:00:00Z");
    const b = trip("bbbbbbbb", "2026-08-25T00:00:00Z");
    expect(
      [a, b].sort(compareOffersLandingTrips).map((item) => item.id),
    ).toEqual(["bbbbbbbb", "aaaaaaaa"]);
  });
});
