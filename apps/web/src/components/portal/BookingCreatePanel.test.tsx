import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BookingCreatePanel } from "@/components/portal/BookingCreatePanel";
import { ApiError } from "@/lib/api/errors";
import type { CustomerBooking, CustomerOffer } from "@/lib/api/types";

const createBooking = vi.fn();
const getTripRequestBooking = vi.fn();

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    createBooking: (...args: unknown[]) => createBooking(...args),
    getTripRequestBooking: (...args: unknown[]) =>
      getTripRequestBooking(...args),
  },
}));

const offer: CustomerOffer = {
  id: "11111111-2222-4333-8444-555555555555",
  trip_request_id: "b32413c8-88e9-4c05-89e5-78afb14f5eb4",
  status: "SELECTED",
  currency: "EUR",
  total_amount_minor: 123456,
  tax_amount_minor: 1000,
  valid_until: "2099-12-01T00:00:00Z",
  operator_legal_name: "Operator",
  aircraft_registration: "EI-ONE",
  aircraft_manufacturer: "Bombardier",
  aircraft_model: "Global 7500",
  aircraft_category: "ULTRA_LONG_RANGE",
  included_services: null,
  excluded_services: null,
  cancellation_policy: null,
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:00Z",
  response_audience: "customer",
};

const booking: CustomerBooking = {
  id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  reference: "SBJ-1234567890ABCDEF",
  trip_request_id: offer.trip_request_id,
  operator_offer_id: offer.id,
  status: "PENDING_OPERATOR_CONFIRMATION",
  currency: "EUR",
  total_amount_minor: 123456,
  tax_amount_minor: 1000,
  operator_legal_name: "Operator",
  aircraft_registration: "EI-ONE",
  aircraft_manufacturer: "Bombardier",
  aircraft_model: "Global 7500",
  aircraft_category: "ULTRA_LONG_RANGE",
  confirmed_at: null,
  cancelled_at: null,
  cancellation_actor: null,
  cancellation_reason: null,
  created_at: "2026-08-26T00:00:00Z",
  updated_at: "2026-08-26T00:00:00Z",
};

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof BookingCreatePanel>> = {},
) {
  return render(
    <BookingCreatePanel
      tripRequestId={offer.trip_request_id}
      tripStatus="SUBMITTED"
      selectedOffer={offer}
      organizationId="org"
      {...overrides}
    />,
  );
}

async function showConfirmation() {
  renderPanel();
  fireEvent.click(
    await screen.findByRole("button", { name: "Create booking request" }),
  );
  return screen.getByRole("button", { name: "Create booking request" });
}

beforeEach(() => {
  createBooking.mockReset();
  getTripRequestBooking.mockReset();
  getTripRequestBooking.mockResolvedValue(null);
});

describe("BookingCreatePanel", () => {
  it("fails closed outside a live selected offer on a submitted trip", () => {
    renderPanel({ tripStatus: "DRAFT" });
    expect(screen.queryByText(/booking request/i)).toBeNull();
  });

  it.each([
    ["missing validity", { valid_until: null }],
    ["invalid validity", { valid_until: "not-a-date" }],
    ["expired validity", { valid_until: "2020-01-01T00:00:00Z" }],
    ["unknown offer status", { status: "FUTURE" }],
  ])("fails closed for %s", (_label, offerOverrides) => {
    renderPanel({
      selectedOffer: { ...offer, ...offerOverrides } as CustomerOffer,
    });
    expect(screen.queryByText(/booking request/i)).toBeNull();
  });

  it.each(["DRAFT", "CANCELLED", "EXPIRED", "FUTURE"])(
    "fails closed for trip status %s",
    (tripStatus) => {
      renderPanel({ tripStatus });
      expect(screen.queryByText(/booking request/i)).toBeNull();
    },
  );

  it("requires explicit confirmation and Keep offer selected makes no POST", async () => {
    await showConfirmation();
    expect(
      screen.getByText(/Operator confirmation is still required/),
    ).toBeTruthy();
    expect(screen.getByText(/No payment is taken/)).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Keep offer selected" }),
    );
    expect(createBooking).not.toHaveBeenCalled();
  });

  it("treats an authoritative 404 as no Booking and allows the eligible CTA", async () => {
    getTripRequestBooking.mockRejectedValueOnce(
      new ApiError(404, "not_found", "raw detail", "client"),
    );
    renderPanel();
    expect(
      await screen.findByRole("button", { name: "Create booking request" }),
    ).toBeTruthy();
    expect(createBooking).not.toHaveBeenCalled();
  });

  it("fails closed when the initial authoritative Booking read fails", async () => {
    getTripRequestBooking.mockRejectedValueOnce(
      new Error("raw network detail"),
    );
    renderPanel();
    expect(
      await screen.findByText("Booking status couldn’t be checked"),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Create booking request" }),
    ).toBeNull();
    expect(screen.queryByText("raw network detail")).toBeNull();
    expect(createBooking).not.toHaveBeenCalled();
  });

  it("uses a synchronous duplicate guard and the exact customer-safe body", async () => {
    let resolve!: (value: CustomerBooking) => void;
    createBooking.mockReturnValue(
      new Promise<CustomerBooking>((done) => {
        resolve = done;
      }),
    );
    const confirm = await showConfirmation();
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(createBooking).toHaveBeenCalledTimes(1);
    expect(createBooking).toHaveBeenCalledWith(
      {
        trip_request_id: offer.trip_request_id,
        operator_offer_id: offer.id,
      },
      "org",
    );
    expect(Object.keys(createBooking.mock.calls[0][0])).toEqual([
      "trip_request_id",
      "operator_offer_id",
    ]);
    expect(
      screen.getByRole("button", { name: "Keep offer selected" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Creating…" }).closest("section"),
    ).toHaveAttribute("aria-busy", "true");
    resolve(booking);
    expect(await screen.findByText("Booking request created")).toBeTruthy();
    expect(screen.getByRole("link", { name: "View bookings" })).toHaveAttribute(
      "href",
      "/portal/bookings",
    );
  });

  it("recovers a 409 with one authoritative read and never retries create", async () => {
    getTripRequestBooking.mockResolvedValueOnce(null);
    createBooking.mockRejectedValueOnce(
      new ApiError(409, "booking_not_allowed", "raw detail", "conflict"),
    );
    getTripRequestBooking.mockResolvedValueOnce(booking);
    fireEvent.click(await showConfirmation());
    expect(await screen.findByText("Booking request created")).toBeTruthy();
    expect(createBooking).toHaveBeenCalledTimes(1);
    expect(getTripRequestBooking).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["404", new ApiError(404, "not_found", "raw detail", "client")],
    ["network failure", new Error("raw network detail")],
  ])(
    "shows safe conflict guidance when 409 recovery ends in %s",
    async (_label, recoveryError) => {
      getTripRequestBooking
        .mockResolvedValueOnce(null)
        .mockRejectedValueOnce(recoveryError);
      createBooking.mockRejectedValueOnce(
        new ApiError(409, "booking_not_allowed", "raw detail", "conflict"),
      );
      fireEvent.click(await showConfirmation());
      expect(await screen.findByText("Booking status changed")).toBeTruthy();
      expect(screen.queryByText("Booking request created")).toBeNull();
      expect(screen.queryByText(/raw detail|raw network detail/)).toBeNull();
      expect(createBooking).toHaveBeenCalledTimes(1);
      expect(getTripRequestBooking).toHaveBeenCalledTimes(2);
    },
  );

  it.each([
    [403, "Booking request not permitted"],
    [404, "Selected offer unavailable"],
    [503, "Booking request couldn’t be created"],
    [0, "Booking request couldn’t be created"],
  ] as const)("hides raw errors for status %s", async (status, expected) => {
    createBooking.mockRejectedValueOnce(
      new ApiError(
        status,
        "unsafe",
        "raw backend secret",
        status === 403
          ? "forbidden"
          : status === 0
            ? "network"
            : status >= 500
              ? "server"
              : "client",
      ),
    );
    fireEvent.click(await showConfirmation());
    expect(await screen.findByText(expected)).toBeTruthy();
    expect(screen.queryByText("raw backend secret")).toBeNull();
  });

  it("suppresses creation when an authoritative Booking already exists", async () => {
    getTripRequestBooking.mockResolvedValueOnce(booking);
    renderPanel();
    expect(await screen.findByText("Booking request created")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /create booking/i }),
    ).toBeNull();
  });
});
