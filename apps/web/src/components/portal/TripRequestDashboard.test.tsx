import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TripRequestDashboard } from "@/components/portal/TripRequestDashboard";
import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";

const listTripRequests = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listTripRequests: (...a: unknown[]) => listTripRequests(...a),
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

function trip(
  id: string,
  status: string,
  createdAt: string,
): CustomerTripRequest {
  return {
    id,
    status,
    version: 1,
    legs: [
      {
        id: `${id}-leg`,
        sequence: 1,
        origin_airport_id: "a1",
        destination_airport_id: "a2",
        departure_at: "2027-01-01T08:00:00Z",
        origin_timezone: "Europe/Dublin",
        destination_timezone: "Europe/London",
        passenger_count: 1,
      },
    ],
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

beforeEach(() => {
  orgContext = { activeOrganizationId: "org-1", hasCustomerContext: true };
  listTripRequests.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe("TripRequestDashboard", () => {
  it("shows real counts and recent requests", async () => {
    listTripRequests.mockResolvedValueOnce([
      trip("aaaaaaaa", "SUBMITTED", "2026-01-03T00:00:00Z"),
      trip("bbbbbbbb", "CANCELLED", "2026-01-02T00:00:00Z"),
      trip("cccccccc", "DRAFT", "2026-01-01T00:00:00Z"),
    ]);
    render(<TripRequestDashboard />);
    await screen.findByText("Recent requests");
    // Stat values: Total 3, Active 2 (SUBMITTED+DRAFT), Submitted 1, Cancelled 1.
    const stat = (label: string) =>
      screen.getByText(label).parentElement?.querySelector(".stat__value")
        ?.textContent;
    expect(stat("Total")).toBe("3");
    expect(stat("Active")).toBe("2");
    expect(stat("Submitted")).toBe("1");
    expect(stat("Cancelled")).toBe("1");
    // Recent list links to detail; newest first.
    expect(
      screen
        .getByRole("link", { name: /Request AAAAAAAA/ })
        .getAttribute("href"),
    ).toBe("/portal/trip-requests/aaaaaaaa");
    // A New trip request CTA is present.
    expect(
      screen
        .getByRole("link", { name: "New trip request" })
        .getAttribute("href"),
    ).toBe("/portal/trip-requests/new");
    // No fabricated commercial data.
    expect(
      screen.queryByText(/\$|price|quote|operator|aircraft|savings/i),
    ).toBeNull();
  });

  it("shows an empty state with a CTA when there are no requests", async () => {
    listTripRequests.mockResolvedValueOnce([]);
    render(<TripRequestDashboard />);
    expect(await screen.findByText("No trip requests yet")).toBeTruthy();
    expect(screen.getByRole("link", { name: "New trip request" })).toBeTruthy();
  });

  it("shows a loading state (no fake zero counts)", () => {
    listTripRequests.mockReturnValueOnce(new Promise(() => {}));
    render(<TripRequestDashboard />);
    expect(screen.getByText("Loading your trip request summary…")).toBeTruthy();
    expect(screen.queryByText("Total")).toBeNull();
  });

  it("distinguishes forbidden from generic error without leaking internals", async () => {
    listTripRequests.mockRejectedValueOnce(
      new ApiError(403, "forbidden", "raw", "forbidden"),
    );
    render(<TripRequestDashboard />);
    expect(
      await screen.findByText("You don’t have access to these trip requests"),
    ).toBeTruthy();
    expect(screen.queryByText(/raw/)).toBeNull();
  });

  it("prompts to link a customer account without a customer context", () => {
    orgContext = { activeOrganizationId: null, hasCustomerContext: false };
    render(<TripRequestDashboard />);
    expect(screen.getByText("No active customer account")).toBeTruthy();
    expect(listTripRequests).not.toHaveBeenCalled();
  });
});
