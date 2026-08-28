import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformComplianceQueue } from "@/components/platform/PlatformComplianceQueue";
import { portalApi } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listPlatformAdmissions: vi.fn(),
    listPlatformEvidence: vi.fn(),
    listPlatformAuthorizations: vi.fn(),
  },
}));

const admission = {
  id: "123e4567-e89b-42d3-a456-426614174000",
  operator_id: "123e4567-e89b-42d3-a456-426614174001",
  operator_legal_name: "Bounded Aviation Ltd",
  operator_trading_name: null,
  operator_country_code: "IE",
  status: "SUBMITTED" as const,
  reason_code: null,
  review_note: null,
  submitted_at: "2026-08-28T10:00:00Z",
  reviewed_at: null,
  created_at: "2026-08-28T09:00:00Z",
  updated_at: "2026-08-28T10:00:00Z",
};

describe("PlatformComplianceQueue", () => {
  beforeEach(() => {
    vi.mocked(portalApi.listPlatformAdmissions).mockResolvedValue([admission]);
    vi.mocked(portalApi.listPlatformEvidence).mockResolvedValue([]);
    vi.mocked(portalApi.listPlatformAuthorizations).mockResolvedValue([]);
  });

  it("loads a bounded actionable queue and switches resource without exhaustive fetch", async () => {
    render(<PlatformComplianceQueue />);
    expect(await screen.findByText("Bounded Aviation Ltd")).toBeInTheDocument();
    expect(portalApi.listPlatformAdmissions).toHaveBeenCalledWith(
      { status: "SUBMITTED", limit: 20, offset: 0 },
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }));
    await waitFor(() =>
      expect(portalApi.listPlatformEvidence).toHaveBeenCalledTimes(1),
    );
    expect(
      await screen.findByText("No matching review work"),
    ).toBeInTheDocument();
  });
});
