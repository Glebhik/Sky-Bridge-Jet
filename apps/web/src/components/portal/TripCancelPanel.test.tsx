import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Mock } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TripCancelPanel } from "@/components/portal/TripCancelPanel";
import { ApiError } from "@/lib/api/errors";
import type { CustomerTripRequest } from "@/lib/api/types";

const cancelTripRequest = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    cancelTripRequest: (...a: unknown[]) => cancelTripRequest(...a),
  },
}));

const TRIP_ID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";

function trip(status: string, version: number): CustomerTripRequest {
  return {
    id: TRIP_ID,
    status,
    version,
    legs: [],
    passengers: [],
    requirements: {
      baggage_notes: null,
      catering_notes: null,
      ground_transport_requested: false,
      special_assistance_notes: null,
      customer_notes: null,
      pet_present: false,
    },
    created_at: "2026-08-25T00:00:00Z",
    updated_at: "2026-08-25T00:00:00Z",
  };
}

let onCancelled: Mock<(updated: CustomerTripRequest) => void>;
let onRefreshNeeded: Mock<() => void>;

function renderPanel(status = "SUBMITTED", version = 2) {
  onCancelled = vi.fn<(updated: CustomerTripRequest) => void>();
  onRefreshNeeded = vi.fn<() => void>();
  render(
    <TripCancelPanel
      trip={trip(status, version)}
      organizationId="org-1"
      onCancelled={onCancelled}
      onRefreshNeeded={onRefreshNeeded}
    />,
  );
}

beforeEach(() => {
  cancelTripRequest.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe("TripCancelPanel", () => {
  it("requires explicit confirmation before any API call", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    // Confirmation prompt appears; no API call yet.
    expect(screen.getByText("Cancel this trip request?")).toBeTruthy();
    expect(cancelTripRequest).not.toHaveBeenCalled();
  });

  it("Keep request dismisses without calling the API", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep request" }));
    expect(cancelTripRequest).not.toHaveBeenCalled();
    expect(screen.queryByText("Cancel this trip request?")).toBeNull();
  });

  it("confirm calls cancel once with the current id/version and reports the CANCELLED trip", async () => {
    cancelTripRequest.mockResolvedValueOnce(trip("CANCELLED", 3));
    renderPanel("SUBMITTED", 2);
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    // The confirm button is the second "Cancel request" (destructive).
    const confirm = screen
      .getAllByRole("button", { name: /Cancel request/ })
      .pop()!;
    fireEvent.click(confirm);
    await waitFor(() => expect(onCancelled).toHaveBeenCalled());
    expect(cancelTripRequest).toHaveBeenCalledTimes(1);
    expect(cancelTripRequest).toHaveBeenCalledWith(TRIP_ID, 2, "org-1");
    expect(onCancelled).toHaveBeenCalledWith(
      expect.objectContaining({ status: "CANCELLED", version: 3 }),
    );
  });

  it("a double confirm results in exactly one cancel call", async () => {
    let resolve: (v: unknown) => void = () => {};
    cancelTripRequest.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderPanel("SUBMITTED", 2);
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    const confirm = screen
      .getAllByRole("button", { name: /Cancel request/ })
      .pop()!;
    fireEvent.click(confirm);
    const pendingConfirm = screen.getByRole("button", { name: "Cancelling…" });
    const keep = screen.getByRole("button", { name: "Keep request" });
    expect(pendingConfirm).toBeDisabled();
    expect(pendingConfirm).toHaveAttribute("aria-busy", "true");
    expect(keep).toBeDisabled();
    expect(cancelTripRequest).toHaveBeenCalledTimes(1);
    fireEvent.click(confirm); // overlapping second confirm
    expect(cancelTripRequest).toHaveBeenCalledTimes(1);
    resolve(trip("CANCELLED", 3));
    await waitFor(() => expect(onCancelled).toHaveBeenCalled());
    expect(cancelTripRequest).toHaveBeenCalledTimes(1);
    expect(onCancelled).toHaveBeenCalledWith(
      expect.objectContaining({ status: "CANCELLED", version: 3 }),
    );
  });

  it("a 409 conflict shows a refresh action and does not report a cancellation", async () => {
    cancelTripRequest.mockRejectedValueOnce(
      new ApiError(409, "conflict", "raw", "conflict"),
    );
    renderPanel("SUBMITTED", 2);
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    fireEvent.click(
      screen.getAllByRole("button", { name: /Cancel request/ }).pop()!,
    );
    await screen.findByText(/changed before it could be cancelled/i);
    expect(onCancelled).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh request" }));
    expect(onRefreshNeeded).toHaveBeenCalledTimes(1);
  });

  it("a server error shows a safe message (no raw backend text) and no optimistic cancel", async () => {
    cancelTripRequest.mockRejectedValueOnce(
      new ApiError(500, "server_error", "RAW-SECRET-TRACE", "server"),
    );
    renderPanel("SUBMITTED", 2);
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    fireEvent.click(
      screen.getAllByRole("button", { name: /Cancel request/ }).pop()!,
    );
    expect(
      await screen.findByText(/We couldn’t cancel your request/i),
    ).toBeTruthy();
    expect(screen.queryByText(/RAW-SECRET-TRACE/)).toBeNull();
    expect(onCancelled).not.toHaveBeenCalled();
  });
});
