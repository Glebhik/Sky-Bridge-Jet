import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalBookingsPage from "@/app/portal/bookings/page";
import { ApiError } from "@/lib/api/errors";
import type { CustomerBooking, CustomerPayment } from "@/lib/api/types";
import { useCustomerPayments } from "@/lib/portal/use-customer-payments";

const listBookings = vi.fn();
const listPayments = vi.fn();
const initiatePayment = vi.fn();
let activeOrganizationId: string | null;
let hasCustomerContext: boolean;
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listBookings: (...args: unknown[]) => listBookings(...args),
    listPayments: (...args: unknown[]) => listPayments(...args),
    initiatePayment: (...args: unknown[]) => initiatePayment(...args),
  },
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

const makePayment = (
  bookingId: string,
  status = "AUTHORIZED",
  overrides: Partial<CustomerPayment> = {},
): CustomerPayment => ({
  id: `payment-${bookingId}`,
  booking_id: bookingId,
  status,
  currency: "EUR",
  total_amount_minor: 123456,
  authorized_amount_minor: status === "AUTHORIZED" ? 123456 : null,
  captured_amount_minor: status === "CAPTURED" ? 123456 : 0,
  refunded_amount_minor: status === "REFUNDED" ? 123456 : 0,
  requires_customer_action: false,
  authorized_at: status === "AUTHORIZED" ? "2026-08-26T11:00:00Z" : null,
  captured_at: status === "CAPTURED" ? "2026-08-26T12:00:00Z" : null,
  cancelled_at: status === "CANCELLED" ? "2026-08-26T12:00:00Z" : null,
  created_at: "2026-08-26T10:00:00Z",
  updated_at: "2026-08-26T11:00:00Z",
  ...overrides,
});

beforeEach(() => {
  listBookings.mockReset();
  listPayments.mockReset();
  initiatePayment.mockReset();
  listPayments.mockResolvedValue([]);
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
      screen.queryByRole("button", { name: /capture|refund|void/i }),
    ).toBeNull();
    expect(
      screen.queryByText(/operator_amount|platform_fee|operator_id/i),
    ).toBeNull();
  });

  it("discovers all displayed Booking IDs once and joins Payments by booking_id", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    const confirmed = makeBooking("CONFIRMED");
    listBookings.mockResolvedValueOnce([pending, confirmed]);
    listPayments.mockResolvedValueOnce([makePayment(confirmed.id)]);
    render(<PortalBookingsPage />);

    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    expect(listPayments).toHaveBeenCalledTimes(1);
    expect(listPayments.mock.calls[0][0]).toEqual([pending.id, confirmed.id]);
    expect(
      screen.getByRole("button", { name: "Authorize payment" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Payment has not been captured by this step."),
    ).toBeTruthy();
  });

  it("requires confirmation and rapid repeated activation produces one POST", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    listBookings.mockResolvedValueOnce([pending]);
    initiatePayment.mockResolvedValueOnce(makePayment(pending.id));
    render(<PortalBookingsPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Authorize payment" }),
    );
    expect(
      screen.getByText(/This step does not capture payment\./),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep reviewing" }));
    expect(initiatePayment).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    const confirm = screen.getByRole("button", { name: "Authorize payment" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    expect(initiatePayment).toHaveBeenCalledTimes(1);
    expect(initiatePayment.mock.calls[0][1]).toEqual({
      idempotency_key: expect.any(String),
    });
  });

  it("fails closed when authoritative discovery fails", async () => {
    listBookings.mockResolvedValueOnce([
      makeBooking("PENDING_OPERATOR_CONFIRMATION"),
    ]);
    listPayments.mockRejectedValueOnce(new Error("raw payment backend detail"));
    render(<PortalBookingsPage />);
    expect(await screen.findByText("Payment status unavailable")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Authorize payment" }),
    ).toBeNull();
    expect(screen.queryByText("raw payment backend detail")).toBeNull();
  });

  it("refreshes exactly once after 409 and never exposes the internal conflict", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    listBookings.mockResolvedValueOnce([pending]);
    listPayments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([makePayment(pending.id)]);
    initiatePayment.mockRejectedValueOnce(
      new ApiError(409, "idempotency_conflict", "internal", "conflict"),
    );
    render(<PortalBookingsPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Authorize payment" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    expect(listPayments).toHaveBeenCalledTimes(2);
    expect(initiatePayment).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/idempotency_conflict|internal/)).toBeNull();
  });

  it("retains one key for an unknown-outcome retry and uses a new key after resolved failure", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    listBookings.mockResolvedValueOnce([pending]);
    initiatePayment
      .mockRejectedValueOnce(
        new ApiError(0, "network_error", "network", "network"),
      )
      .mockResolvedValueOnce(makePayment(pending.id, "AUTHORIZATION_FAILED"))
      .mockResolvedValueOnce(makePayment(pending.id));
    render(<PortalBookingsPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Authorize payment" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    expect(
      await screen.findByText("We could not confirm the authorization result."),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry same authorization attempt" }),
    );
    expect(
      await screen.findByText("Payment authorization was not completed"),
    ).toBeTruthy();
    expect(initiatePayment.mock.calls[1][1]).toEqual(
      initiatePayment.mock.calls[0][1],
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Try authorization again" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    expect(initiatePayment.mock.calls[2][1]).not.toEqual(
      initiatePayment.mock.calls[1][1],
    );
  });

  it("allows only authoritative refresh or same-key retry while an outcome is unknown", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    listBookings.mockResolvedValueOnce([pending]);
    initiatePayment
      .mockRejectedValueOnce(
        new ApiError(0, "network_error", "network", "network"),
      )
      .mockResolvedValueOnce(makePayment(pending.id));
    render(<PortalBookingsPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Authorize payment" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    expect(
      await screen.findByText("We could not confirm the authorization result."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Authorize payment" }),
    ).toBeNull();
    expect(
      screen.getAllByRole("button").map((button) => button.textContent),
    ).toEqual([
      "Refresh status",
      "Refresh Payment status",
      "Retry same authorization attempt",
    ]);
    fireEvent.click(
      screen.getByRole("button", { name: "Retry same authorization attempt" }),
    );
    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    expect(initiatePayment).toHaveBeenCalledTimes(2);
    expect(initiatePayment.mock.calls[1][1]).toEqual(
      initiatePayment.mock.calls[0][1],
    );
    expect(
      screen.queryByRole("button", {
        name: "Retry same authorization attempt",
      }),
    ).toBeNull();
  });

  it("fails closed in the hook when a normal caller bypasses unknown-outcome UI", async () => {
    const uuid = vi
      .spyOn(crypto, "randomUUID")
      .mockReturnValue("00000000-0000-4000-8000-000000000001");
    initiatePayment
      .mockRejectedValueOnce(
        new ApiError(0, "network_error", "network", "network"),
      )
      .mockResolvedValueOnce(makePayment("booking"));
    const bookingIds = ["booking"] as const;
    const { result } = renderHook(() =>
      useCustomerPayments(bookingIds, "org", true),
    );
    await waitFor(() => expect(result.current.state.status).toBe("ready"));

    await act(() => result.current.authorize("booking"));
    await act(() => result.current.authorize("booking"));
    expect(initiatePayment).toHaveBeenCalledTimes(1);
    expect(uuid).toHaveBeenCalledTimes(1);

    await act(() => result.current.authorize("booking", true));
    expect(initiatePayment).toHaveBeenCalledTimes(2);
    expect(initiatePayment.mock.calls[1][1]).toEqual(
      initiatePayment.mock.calls[0][1],
    );
    expect(uuid).toHaveBeenCalledTimes(1);
    uuid.mockRestore();
  });

  it("clears an unknown attempt when authoritative refresh finds AUTHORIZED", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    listBookings.mockResolvedValueOnce([pending]);
    listPayments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([makePayment(pending.id)]);
    initiatePayment.mockRejectedValueOnce(
      new ApiError(0, "network_error", "network", "network"),
    );
    render(<PortalBookingsPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Authorize payment" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    expect(
      await screen.findByText("We could not confirm the authorization result."),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Refresh Payment status" }),
    );
    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    expect(screen.queryByText("Result not confirmed")).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: "Retry same authorization attempt",
      }),
    ).toBeNull();
    expect(initiatePayment).toHaveBeenCalledTimes(1);
  });

  it("cannot reuse an unresolved key after the organization identity changes", async () => {
    const bookingIds = ["booking"] as const;
    initiatePayment
      .mockRejectedValueOnce(
        new ApiError(0, "network_error", "network", "network"),
      )
      .mockResolvedValueOnce(makePayment("booking"));
    const { result, rerender } = renderHook(
      ({ organizationId }: { organizationId: string }) =>
        useCustomerPayments(bookingIds, organizationId, true),
      { initialProps: { organizationId: "org-a" } },
    );
    await waitFor(() => expect(result.current.state.status).toBe("ready"));
    await act(() => result.current.authorize("booking"));
    const oldAttempt = initiatePayment.mock.calls[0][1];

    rerender({ organizationId: "org-b" });
    await waitFor(() => expect(listPayments).toHaveBeenCalledTimes(2));
    await act(() => result.current.authorize("booking"));
    expect(initiatePayment).toHaveBeenCalledTimes(2);
    expect(initiatePayment.mock.calls[1][1]).not.toEqual(oldAttempt);
    expect(initiatePayment.mock.calls[1][2]).toBe("org-b");
  });

  it("does not let an older discovery response overwrite a successful POST", async () => {
    const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
    let resolveOldRead!: (value: readonly CustomerPayment[]) => void;
    const oldRead = new Promise<readonly CustomerPayment[]>((resolve) => {
      resolveOldRead = resolve;
    });
    listBookings.mockResolvedValue([pending]);
    listPayments.mockResolvedValueOnce([]).mockReturnValueOnce(oldRead);
    initiatePayment.mockResolvedValueOnce(makePayment(pending.id));
    render(<PortalBookingsPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Refresh status" }),
    );
    await waitFor(() => expect(listPayments).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    fireEvent.click(screen.getByRole("button", { name: "Authorize payment" }));
    expect(await screen.findByText("Payment authorized")).toBeTruthy();
    resolveOldRead([]);
    await Promise.resolve();
    expect(screen.getByText("Payment authorized")).toBeTruthy();
    expect(
      screen.queryByText("No Payment authorization has been recorded"),
    ).toBeNull();
  });

  it.each([
    [403, "forbidden", "You do not have permission to authorize this Payment."],
    [
      404,
      "client",
      "This Booking is no longer available for Payment authorization.",
    ],
  ] as const)(
    "handles %s without raw backend detail",
    async (status, kind, safeCopy) => {
      const pending = makeBooking("PENDING_OPERATOR_CONFIRMATION");
      listBookings.mockResolvedValueOnce([pending]);
      initiatePayment.mockRejectedValueOnce(
        new ApiError(status, "raw_internal_code", "raw backend detail", kind),
      );
      render(<PortalBookingsPage />);
      fireEvent.click(
        await screen.findByRole("button", { name: "Authorize payment" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Authorize payment" }),
      );
      expect(await screen.findByText(safeCopy)).toBeTruthy();
      expect(
        screen.queryByText(/raw backend detail|raw_internal_code/),
      ).toBeNull();
    },
  );

  it("invalidates Payment state when active organization identity changes", async () => {
    const first = {
      ...makeBooking("CONFIRMED"),
      id: "booking-org-a",
      reference: "ORG-A",
    };
    const second = {
      ...makeBooking("CONFIRMED"),
      id: "booking-org-b",
      reference: "ORG-B",
    };
    listBookings.mockResolvedValueOnce([first]).mockResolvedValueOnce([second]);
    listPayments
      .mockResolvedValueOnce([makePayment(first.id)])
      .mockResolvedValueOnce([]);
    const view = render(<PortalBookingsPage />);
    expect(await screen.findByText("Payment authorized")).toBeTruthy();

    activeOrganizationId = "org-b";
    view.rerender(<PortalBookingsPage />);
    expect(await screen.findByText("ORG-B")).toBeTruthy();
    expect(
      await screen.findByText(
        "No Payment authorization has been recorded for this Booking.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("ORG-A")).toBeNull();
    expect(listPayments.mock.calls[1][1]).toBe("org-b");
  });
});
