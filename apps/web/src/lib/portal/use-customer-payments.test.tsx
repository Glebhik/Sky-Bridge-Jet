import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomerPayment } from "@/lib/api/types";
import { useCustomerPayments } from "@/lib/portal/use-customer-payments";

const { listPayments, initiatePayment } = vi.hoisted(() => ({
  listPayments: vi.fn(),
  initiatePayment: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  portalApi: { listPayments, initiatePayment },
}));

const basePayment: CustomerPayment = {
  id: "payment-1",
  booking_id: "booking-1",
  status: "CREATED",
  currency: "EUR",
  total_amount_minor: 10000,
  authorized_amount_minor: null,
  captured_amount_minor: 0,
  refunded_amount_minor: 0,
  requires_customer_action: false,
  authorized_at: null,
  captured_at: null,
  cancelled_at: null,
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
};
const bookingIds = ["booking-1"] as const;

describe("useCustomerPayments transient client action", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listPayments.mockResolvedValue([basePayment]);
    initiatePayment.mockResolvedValue({
      ...basePayment,
      requires_customer_action: true,
      client_action: {
        action_type: "stripe_confirm_payment",
        client_secret: "pi_secret_memory_only",
      },
    });
  });

  it("keeps the client secret in memory only and clears it on organization change", async () => {
    const { result, rerender, unmount } = renderHook(
      ({ organizationId }) =>
        useCustomerPayments(bookingIds, organizationId, true),
      { initialProps: { organizationId: "org-a" } },
    );
    await waitFor(() => expect(result.current.state.status).toBe("ready"));

    await act(async () => result.current.authorize("booking-1"));
    expect(result.current.clientActions["booking-1"]?.client_secret).toBe(
      "pi_secret_memory_only",
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);

    rerender({ organizationId: "org-b" });
    await waitFor(() => expect(result.current.clientActions).toEqual({}));
    unmount();
    expect(document.body.textContent).not.toContain("pi_secret_memory_only");
  });
});
