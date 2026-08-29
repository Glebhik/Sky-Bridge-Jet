import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformPilotGovernance } from "@/components/platform/PlatformPilotGovernance";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { PilotParticipant, PilotState } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    getPilotState: vi.fn(),
    listPilotParticipants: vi.fn(),
    listPilotAudits: vi.fn(),
    updatePilotState: vi.fn(),
    createPilotParticipant: vi.fn(),
    updatePilotParticipant: vi.fn(),
  },
}));

const state: PilotState = {
  id: "00000000-0000-0000-0000-00000000010b",
  mode: "CONTROLLED_EXTERNAL",
  payment_initiation_enabled: false,
  version: 3,
  updated_at: "2026-08-29T12:00:00Z",
};
const participant: PilotParticipant = {
  id: "123e4567-e89b-42d3-a456-426614174000",
  organization_id: "123e4567-e89b-42d3-a456-426614174001",
  organization_name: "Pilot Customer",
  participant_type: "CUSTOMER",
  status: "ACTIVE",
  version: 2,
  created_at: "2026-08-29T12:00:00Z",
  updated_at: "2026-08-29T12:00:00Z",
};

describe("PlatformPilotGovernance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(portalApi.getPilotState).mockResolvedValue(state);
    vi.mocked(portalApi.listPilotParticipants).mockResolvedValue([participant]);
    vi.mocked(portalApi.listPilotAudits).mockResolvedValue([]);
    vi.mocked(portalApi.updatePilotState).mockResolvedValue(state);
    vi.mocked(portalApi.updatePilotParticipant).mockResolvedValue(participant);
  });

  it("loads bounded authoritative state and exposes factual controls", async () => {
    render(<PlatformPilotGovernance canManage />);
    expect(await screen.findByText("Pilot Customer")).toBeInTheDocument();
    expect(portalApi.listPilotParticipants).toHaveBeenCalledWith(
      0,
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: "PAUSED" })).toBeEnabled();
    expect(screen.getByText(/Payment initiation paused/)).toBeInTheDocument();
    expect(screen.getByText(/NO REAL MONEY/)).toBeInTheDocument();
  });

  it("does not retry a stale mutation and refreshes authoritative state", async () => {
    vi.mocked(portalApi.updatePilotParticipant).mockRejectedValueOnce(
      new ApiError(409, "pilot_governance_conflict", "changed", "conflict"),
    );
    render(<PlatformPilotGovernance canManage />);
    await screen.findByText("Pilot Customer");
    fireEvent.click(screen.getByRole("button", { name: "Suspend" }));
    expect(
      await screen.findByText(/authoritative state changed/i),
    ).toBeInTheDocument();
    expect(portalApi.updatePilotParticipant).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(portalApi.getPilotState).toHaveBeenCalledTimes(2),
    );
  });

  it("explains that PAUSED blocks new journeys without cancelling bookings", async () => {
    vi.mocked(portalApi.getPilotState).mockResolvedValue({
      ...state,
      mode: "PAUSED",
    });
    render(<PlatformPilotGovernance canManage />);
    expect(
      await screen.findByText(
        /New controlled journeys are paused\. Existing bookings remain unchanged\./,
      ),
    ).toBeInTheDocument();
  });

  it("keeps support read-only while preserving authoritative reads", async () => {
    render(<PlatformPilotGovernance canManage={false} />);
    expect(await screen.findByText("Pilot Customer")).toBeInTheDocument();
    expect(screen.getByText(/Read-only access/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "PAUSED" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Suspend" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Revoke" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create invitation" }),
    ).not.toBeInTheDocument();
  });
});
