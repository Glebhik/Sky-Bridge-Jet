import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperatorBookingQueue } from "@/components/operator/OperatorBookingQueue";
import { ApiError } from "@/lib/api/errors";
import type { OperatorBooking } from "@/lib/api/types";

const listOperatorBookings = vi.fn();
const confirmOperatorBooking = vi.fn();
const rejectOperatorBooking = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listOperatorBookings: (...args: unknown[]) => listOperatorBookings(...args),
    confirmOperatorBooking: (...args: unknown[]) =>
      confirmOperatorBooking(...args),
    rejectOperatorBooking: (...args: unknown[]) =>
      rejectOperatorBooking(...args),
  },
}));

const booking = {
  booking_id: "11111111-2222-4333-8444-555555555555",
  reference: "SBJ-95B",
  status: "PENDING_OPERATOR_CONFIRMATION",
  trip_request_id: "trip",
  operator_offer_id: "offer",
  currency: "EUR",
  operator_amount_minor: 120000,
  operator_legal_name: "Factual Air",
  aircraft_registration: "EI-REAL",
  aircraft_manufacturer: "Cessna",
  aircraft_model: "Citation",
  aircraft_category: "LIGHT_JET",
  created_at: "2026-08-26T00:00:00Z",
  legs: [
    {
      sequence: 1,
      origin_airport_code: "EIDW",
      destination_airport_code: "EGLF",
      departure_at: "2026-12-01T14:00:00Z",
      passenger_count: 2,
    },
  ],
} as const;
const organizations = [
  { id: "org-1", role: "OPERATOR_OPERATIONS", canDecide: true },
];

beforeEach(() => {
  listOperatorBookings.mockReset();
  confirmOperatorBooking.mockReset();
  rejectOperatorBooking.mockReset();
});

describe("OperatorBookingQueue", () => {
  it("does not load without an operator organization", () => {
    render(<OperatorBookingQueue organizations={[]} />);
    expect(screen.getByText("Operator access required")).toBeTruthy();
    expect(listOperatorBookings).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: /confirm|reject/i }),
    ).toBeNull();
  });

  it("auto-resolves exactly one operator organization", async () => {
    listOperatorBookings.mockResolvedValue([]);
    render(<OperatorBookingQueue organizations={organizations} />);
    expect(await screen.findByText("No pending booking requests")).toBeTruthy();
    expect(listOperatorBookings).toHaveBeenCalledTimes(1);
    expect(listOperatorBookings).toHaveBeenCalledWith("org-1");
  });

  it("requires an explicit multi-organization choice and ignores stale results", async () => {
    let resolveA!: (value: readonly OperatorBooking[]) => void;
    const bookingA = {
      ...booking,
      booking_id: "booking-a",
      reference: "SBJ-A",
    };
    const bookingB = {
      ...booking,
      booking_id: "booking-b",
      reference: "SBJ-B",
    };
    listOperatorBookings.mockImplementation((organizationId: string) => {
      if (organizationId === "org-a")
        return new Promise((done) => {
          resolveA = done;
        });
      return Promise.resolve([bookingB]);
    });
    render(
      <OperatorBookingQueue
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN", canDecide: true },
          { id: "org-b", role: "OPERATOR_OPERATIONS", canDecide: true },
        ]}
      />,
    );
    expect(
      screen.getByText("Choose operator organization", {
        selector: ".state__title",
      }),
    ).toBeTruthy();
    expect(listOperatorBookings).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Review decision" }),
    ).toBeNull();

    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    expect(
      screen.getByRole("option", {
        name: "Operator organization 1 — OPERATOR_ADMIN",
      }),
    ).toBeTruthy();
    fireEvent.change(chooser, { target: { value: "org-a" } });
    await waitFor(() =>
      expect(listOperatorBookings).toHaveBeenCalledWith("org-a"),
    );
    fireEvent.change(chooser, { target: { value: "org-b" } });
    expect(await screen.findByText("SBJ-B")).toBeTruthy();
    expect(listOperatorBookings).toHaveBeenCalledWith("org-b");
    resolveA([bookingA]);
    await waitFor(() => expect(screen.queryByText("SBJ-A")).toBeNull());
    expect(screen.getByText("SBJ-B")).toBeTruthy();
  });

  it.each(["OPERATOR_ADMIN", "OPERATOR_OPERATIONS"])(
    "shows decision controls for %s",
    async (role) => {
      listOperatorBookings.mockResolvedValue([booking]);
      render(
        <OperatorBookingQueue
          organizations={[{ id: "org-1", role, canDecide: true }]}
        />,
      );
      expect(
        await screen.findByRole("button", { name: "Review decision" }),
      ).toBeTruthy();
    },
  );

  it("shows the queue without decision controls for OPERATOR_SALES", async () => {
    listOperatorBookings.mockResolvedValue([booking]);
    render(
      <OperatorBookingQueue
        organizations={[
          { id: "org-1", role: "OPERATOR_SALES", canDecide: false },
        ]}
      />,
    );
    expect(await screen.findByText("SBJ-95B")).toBeTruthy();
    expect(screen.getByText("Read-only access")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /confirm|reject|review/i }),
    ).toBeNull();
  });

  it("renders loading, empty and factual populated states without PII/payment", async () => {
    let resolve!: (value: readonly (typeof booking)[]) => void;
    listOperatorBookings.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const view = render(<OperatorBookingQueue organizations={organizations} />);
    expect(screen.getByText("Loading booking requests…")).toBeTruthy();
    resolve([]);
    expect(await screen.findByText("No pending booking requests")).toBeTruthy();
    view.unmount();
    listOperatorBookings.mockResolvedValue([booking]);
    render(<OperatorBookingQueue organizations={organizations} />);
    expect(await screen.findByText("SBJ-95B")).toBeTruthy();
    expect(screen.getByText(/EIDW → EGLF/)).toBeTruthy();
    expect(screen.queryByText(/customer|payment|email/i)).toBeNull();
  });

  it("guards overlapping decisions and refreshes authoritative queue", async () => {
    listOperatorBookings
      .mockResolvedValueOnce([booking])
      .mockResolvedValueOnce([]);
    let resolve!: () => void;
    confirmOperatorBooking.mockReturnValue(
      new Promise<void>((done) => {
        resolve = done;
      }),
    );
    render(<OperatorBookingQueue organizations={organizations} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review decision" }),
    );
    const confirm = screen.getByRole("button", { name: "Confirm booking" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(confirmOperatorBooking).toHaveBeenCalledTimes(1);
    expect(confirm.closest("[aria-busy]")?.getAttribute("aria-busy")).toBe(
      "true",
    );
    resolve();
    await waitFor(() =>
      expect(screen.getByText("No pending booking requests")).toBeTruthy(),
    );
  });

  it("guards double reject and confirm/reject overlap", async () => {
    listOperatorBookings
      .mockResolvedValueOnce([booking])
      .mockResolvedValueOnce([]);
    let resolve!: () => void;
    rejectOperatorBooking.mockReturnValue(
      new Promise<void>((done) => {
        resolve = done;
      }),
    );
    render(<OperatorBookingQueue organizations={organizations} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review decision" }),
    );
    const reject = screen.getByRole("button", { name: "Reject booking" });
    fireEvent.click(reject);
    fireEvent.click(reject);
    fireEvent.click(screen.getByRole("button", { name: "Confirm booking" }));
    expect(rejectOperatorBooking).toHaveBeenCalledTimes(1);
    expect(rejectOperatorBooking).toHaveBeenCalledWith(
      booking.booking_id,
      { reason: "AIRCRAFT_UNAVAILABLE" },
      "org-1",
    );
    expect(confirmOperatorBooking).not.toHaveBeenCalled();
    resolve();
    await waitFor(() =>
      expect(screen.getByText("No pending booking requests")).toBeTruthy(),
    );
  });

  it("does not retry a 409 and suppresses raw errors", async () => {
    listOperatorBookings
      .mockResolvedValueOnce([booking])
      .mockResolvedValueOnce([]);
    confirmOperatorBooking.mockRejectedValue(
      new ApiError(409, "conflict", "secret compliance detail", "conflict"),
    );
    render(<OperatorBookingQueue organizations={organizations} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review decision" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm booking" }));
    expect(await screen.findByText(/could not be refreshed/i)).toBeTruthy();
    expect(confirmOperatorBooking).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/secret compliance detail/i)).toBeNull();
  });
});
