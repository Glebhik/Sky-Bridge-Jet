import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformPaymentDetail } from "@/components/platform/PlatformPaymentDetail";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { PlatformPaymentDetail as Detail } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    getPlatformPayment: vi.fn(),
    reconcilePlatformPaymentOperation: vi.fn(),
  },
}));

const detail: Detail = {
  id: "123e4567-e89b-42d3-a456-426614174001",
  reference: "PAY-EXCEPTION",
  booking_id: "123e4567-e89b-42d3-a456-426614174002",
  status: "CREATED",
  currency: "EUR",
  payment_provider: "FAKE",
  operator_amount_minor: 100000,
  platform_fee_minor: 20000,
  tax_amount_minor: 5000,
  total_amount_minor: 125000,
  authorized_amount_minor: null,
  captured_amount_minor: 0,
  refunded_amount_minor: 0,
  provider_payment_reference: null,
  provider_status: null,
  requires_customer_action: false,
  authorized_at: null,
  captured_at: null,
  cancelled_at: null,
  created_at: "2026-08-28T10:00:00Z",
  updated_at: "2026-08-28T10:01:00Z",
  operations: [
    {
      id: "123e4567-e89b-42d3-a456-426614174000",
      payment_id: "123e4567-e89b-42d3-a456-426614174001",
      operation: "AUTHORIZE",
      result: "UNKNOWN",
      amount_minor: 125000,
      provider_kind: "FAKE",
      provider_reference: null,
      failure_code: "provider_outcome_unknown",
      correlation_id: "123e4567-e89b-42d3-a456-426614174003",
      attempt_count: 1,
      created_at: "2026-08-28T10:00:00Z",
      updated_at: "2026-08-28T10:01:00Z",
    },
  ],
};

describe("PlatformPaymentDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(portalApi.getPlatformPayment).mockResolvedValue(detail);
    vi.mocked(portalApi.reconcilePlatformPaymentOperation).mockResolvedValue({
      ...detail,
      status: "AUTHORIZED",
      operations: [
        { ...detail.operations[0], result: "SUCCEEDED", attempt_count: 2 },
      ],
    });
  });
  it("hides mutation control from read-only users", async () => {
    render(<PlatformPaymentDetail id={detail.id} canOperate={false} />);
    await screen.findByText("PAY-EXCEPTION");
    expect(
      screen.queryByRole("button", { name: "Reconcile existing operation" }),
    ).toBeNull();
  });
  it("requires deliberate confirmation and sends one bodyless command", async () => {
    render(<PlatformPaymentDetail id={detail.id} canOperate />);
    await screen.findByText("PAY-EXCEPTION");
    fireEvent.click(
      screen.getByRole("button", { name: "Reconcile existing operation" }),
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "reuses the existing logical operation",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm reconciliation" }),
    );
    await waitFor(() =>
      expect(portalApi.reconcilePlatformPaymentOperation).toHaveBeenCalledTimes(
        1,
      ),
    );
    expect(portalApi.reconcilePlatformPaymentOperation).toHaveBeenCalledWith(
      detail.operations[0].id,
    );
  });
  it("does not retry a 409 and performs one authoritative refresh", async () => {
    vi.mocked(portalApi.reconcilePlatformPaymentOperation).mockRejectedValue(
      new ApiError(409, "conflict", "Conflict", "conflict"),
    );
    render(<PlatformPaymentDetail id={detail.id} canOperate />);
    await screen.findByText("PAY-EXCEPTION");
    fireEvent.click(
      screen.getByRole("button", { name: "Reconcile existing operation" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm reconciliation" }),
    );
    expect(await screen.findByText(/no retry was sent/i)).toBeInTheDocument();
    expect(portalApi.reconcilePlatformPaymentOperation).toHaveBeenCalledTimes(
      1,
    );
    expect(portalApi.getPlatformPayment).toHaveBeenCalledTimes(2);
  });
  it("does not claim success or retry after an unknown transport outcome", async () => {
    vi.mocked(portalApi.reconcilePlatformPaymentOperation).mockRejectedValue(
      new TypeError("response lost"),
    );
    render(<PlatformPaymentDetail id={detail.id} canOperate />);
    await screen.findByText("PAY-EXCEPTION");
    fireEvent.click(
      screen.getByRole("button", { name: "Reconcile existing operation" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm reconciliation" }),
    );
    expect(
      await screen.findByText(/result could not be confirmed/i),
    ).toBeInTheDocument();
    expect(portalApi.reconcilePlatformPaymentOperation).toHaveBeenCalledTimes(
      1,
    );
    expect(screen.queryByText("AUTHORIZED")).toBeNull();
  });
  it("ignores a stale Payment A detail after navigating to Payment B", async () => {
    let resolveA: (value: Detail) => void = () => undefined;
    const pendingA = new Promise<Detail>((resolve) => {
      resolveA = resolve;
    });
    const detailB = { ...detail, id: "payment-b", reference: "PAYMENT-B" };
    vi.mocked(portalApi.getPlatformPayment).mockImplementation((id) =>
      id === detail.id ? pendingA : Promise.resolve(detailB),
    );
    const view = render(
      <PlatformPaymentDetail id={detail.id} canOperate={false} />,
    );
    view.rerender(<PlatformPaymentDetail id={detailB.id} canOperate={false} />);
    expect(await screen.findByText("PAYMENT-B")).toBeInTheDocument();
    resolveA(detail);
    await Promise.resolve();
    expect(screen.queryByText("PAY-EXCEPTION")).toBeNull();
  });
});
