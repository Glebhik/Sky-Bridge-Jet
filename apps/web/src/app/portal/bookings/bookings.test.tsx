import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalBookingsPage from "@/app/portal/bookings/page";
import type { CustomerBooking } from "@/lib/api/types";

const listBookings = vi.fn();
let activeOrganizationId: string | null;
let hasCustomerContext: boolean;
vi.mock("@/lib/api/client", () => ({
  portalApi: { listBookings: (...args: unknown[]) => listBookings(...args) },
}));
vi.mock("@/components/session/org-context", () => ({
  useActiveOrganization: () => ({
    activeOrganizationId,
    hasCustomerContext,
  }),
}));

const makeBooking = (status: CustomerBooking["status"]): CustomerBooking => ({
  id: status,
  reference: `SBJ-${status}`,
  trip_request_id: "trip",
  operator_offer_id: "offer",
  status,
  currency: "EUR",
  total_amount_minor: 123456,
  tax_amount_minor: 1000,
  operator_legal_name: "A very long factual operator legal name Limited",
  aircraft_registration: "EI-LONG",
  aircraft_manufacturer: "Bombardier",
  aircraft_model: "Global 7500",
  aircraft_category: "ULTRA_LONG_RANGE",
  confirmed_at: status === "CONFIRMED" ? "2026-08-26T10:00:00Z" : null,
  cancelled_at: status === "CANCELLED" ? "2026-08-26T10:00:00Z" : null,
  cancellation_actor: status === "CANCELLED" ? "CUSTOMER" : null,
  cancellation_reason: status === "CANCELLED" ? "OTHER" : null,
  created_at: "2026-08-26T09:00:00Z",
  updated_at: "2026-08-26T10:00:00Z",
});

beforeEach(() => {
  listBookings.mockReset();
  activeOrganizationId = "org";
  hasCustomerContext = true;
});

describe("customer Bookings page", () => {
  it("renders loading then empty state", async () => {
    listBookings.mockResolvedValueOnce([]);
    render(<PortalBookingsPage />);
    expect(screen.getByText("Loading your bookings…")).toBeTruthy();
    expect(await screen.findByText("No bookings yet")).toBeTruthy();
  });

  it("isolates errors and hides raw detail", async () => {
    listBookings.mockRejectedValueOnce(new Error("raw backend secret"));
    render(<PortalBookingsPage />);
    expect(
      await screen.findByText("We couldn’t load your bookings"),
    ).toBeTruthy();
    expect(screen.queryByText("raw backend secret")).toBeNull();
  });

  it("does not read without an active customer context", () => {
    activeOrganizationId = null;
    hasCustomerContext = false;
    render(<PortalBookingsPage />);
    expect(screen.getByText("No active customer account")).toBeTruthy();
    expect(listBookings).not.toHaveBeenCalled();
  });

  it("retains the list, keeps one stable safe warning, and recovers manually", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    listBookings
      .mockResolvedValueOnce([pending])
      .mockRejectedValueOnce(new Error("raw backend secret"))
      .mockRejectedValueOnce(new Error("raw backend secret"))
      .mockResolvedValueOnce([makeBooking("CONFIRMED")]);
    render(<PortalBookingsPage />);
    expect(await screen.findByText(pending.reference)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    const warning = await screen.findByText(
      "Booking status could not be refreshed.",
    );
    expect(screen.getByText(pending.reference)).toBeTruthy();
    expect(screen.queryByText("raw backend secret")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() => expect(listBookings).toHaveBeenCalledTimes(3));
    expect(screen.getByText("Booking status could not be refreshed.")).toBe(
      warning,
    );

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(await screen.findByText("Confirmed by the operator")).toBeTruthy();
    expect(
      screen.queryByText("Booking status could not be refreshed."),
    ).toBeNull();
  });

  it("renders every authoritative state and factual customer-safe fields", async () => {
    listBookings.mockResolvedValueOnce([
      makeBooking("PENDING_OPERATOR_CONFIRMATION"),
      makeBooking("CONFIRMED"),
      makeBooking("REJECTED"),
      makeBooking("CANCELLED"),
    ]);
    render(<PortalBookingsPage />);
    expect(
      await screen.findByText("Awaiting operator confirmation"),
    ).toBeTruthy();
    expect(screen.getByText("Confirmed by the operator")).toBeTruthy();
    expect(
      screen.getByText("The operator could not confirm this booking"),
    ).toBeTruthy();
    expect(screen.getByText("This booking was cancelled")).toBeTruthy();
    expect(screen.getAllByText(/A very long factual operator/)).toHaveLength(4);
    expect(screen.getAllByText(/Bombardier Global 7500/)).toHaveLength(4);
    expect(screen.getAllByText("€1,234.56 EUR")).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /pay|cancel|confirm|reject/i }),
    ).toBeNull();
    expect(
      screen.queryByText(/operator_amount|platform_fee|operator_id/i),
    ).toBeNull();
  });
});
