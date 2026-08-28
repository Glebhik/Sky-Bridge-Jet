import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformPaymentExceptions } from "@/components/platform/PlatformPaymentExceptions";
import { portalApi } from "@/lib/api/client";
import type { PlatformPaymentException } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  portalApi: { listPlatformPaymentExceptions: vi.fn() },
}));

const item: PlatformPaymentException = {
  id: "123e4567-e89b-42d3-a456-426614174000",
  payment_id: "123e4567-e89b-42d3-a456-426614174001",
  booking_id: "123e4567-e89b-42d3-a456-426614174002",
  payment_reference: "PAY-EXCEPTION",
  payment_status: "CREATED",
  currency: "EUR",
  total_amount_minor: 125000,
  authorized_amount_minor: null,
  captured_amount_minor: 0,
  refunded_amount_minor: 0,
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
  can_reconcile: true,
};

describe("PlatformPaymentExceptions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(portalApi.listPlatformPaymentExceptions).mockResolvedValue([
      item,
    ]);
  });
  it("loads only one bounded page", async () => {
    render(<PlatformPaymentExceptions />);
    expect(await screen.findByText("PAY-EXCEPTION")).toBeInTheDocument();
    expect(portalApi.listPlatformPaymentExceptions).toHaveBeenCalledWith(
      { result: undefined, operation: undefined, limit: 20, offset: 0 },
      expect.any(AbortSignal),
    );
  });
  it("changes filters without exhaustive pagination", async () => {
    render(<PlatformPaymentExceptions />);
    await screen.findByText("PAY-EXCEPTION");
    fireEvent.change(screen.getByLabelText("Operation result"), {
      target: { value: "UNKNOWN" },
    });
    await waitFor(() =>
      expect(portalApi.listPlatformPaymentExceptions).toHaveBeenLastCalledWith(
        expect.objectContaining({ result: ["UNKNOWN"], offset: 0 }),
        expect.any(AbortSignal),
      ),
    );
  });
});
