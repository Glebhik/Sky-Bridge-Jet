import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperatorBookingHistory } from "@/components/operator/OperatorBookingHistory";
import { ApiError } from "@/lib/api/errors";
import type { OperatorBookingReadView } from "@/lib/api/types";

const listHistory = vi.fn();
const getBooking = vi.fn();
vi.mock("@/lib/api/client", () => ({
  portalApi: {
    listOperatorBookingHistory: (...args: unknown[]) => listHistory(...args),
    getOperatorBooking: (...args: unknown[]) => getBooking(...args),
  },
}));

const organizations = [{ id: "org-a", role: "OPERATOR_ADMIN" }];
const item: OperatorBookingReadView = {
  id: "11111111-2222-4333-8444-555555555555",
  reference: "SBJ-HISTORY",
  status: "PENDING_OPERATOR_CONFIRMATION",
  trip_request_id: "trip-safe",
  operator_offer_id: "offer-safe",
  aircraft_id: "aircraft-safe",
  currency: "EUR",
  operator_amount_minor: 123400,
  operator_legal_name: "Factual Air",
  aircraft_registration: "EI-SAFE",
  aircraft_manufacturer: "Cessna",
  aircraft_model: "Citation CJ3",
  aircraft_category: "LIGHT_JET",
  legs: [
    {
      sequence: 1,
      origin_airport_code: "EIDW",
      destination_airport_code: "EGLF",
      departure_at: "2026-12-01T14:00:00Z",
      passenger_count: 2,
    },
  ],
  confirmed_at: null,
  rejected_at: null,
  cancelled_at: null,
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

beforeEach(() => {
  listHistory.mockReset();
  getBooking.mockReset();
});

describe("OperatorBookingHistory", () => {
  it("requires an operator organization and makes no request", () => {
    render(<OperatorBookingHistory organizations={[]} />);
    expect(screen.getByText("Operator access required")).toBeTruthy();
    expect(listHistory).not.toHaveBeenCalled();
  });

  it("renders loading, empty, populated and all factual lifecycle states", async () => {
    let resolve!: (value: readonly OperatorBookingReadView[]) => void;
    listHistory.mockReturnValueOnce(new Promise((done) => (resolve = done)));
    const view = render(
      <OperatorBookingHistory organizations={organizations} />,
    );
    expect(screen.getByText("Loading booking history…")).toBeTruthy();
    resolve([]);
    expect(await screen.findByText("No booking history")).toBeTruthy();
    view.unmount();

    const states: readonly OperatorBookingReadView[] = [
      item,
      {
        ...item,
        id: "2",
        reference: "SBJ-C",
        status: "CONFIRMED",
        confirmed_at: "2026-08-28T10:00:00Z",
      },
      {
        ...item,
        id: "3",
        reference: "SBJ-R",
        status: "REJECTED",
        rejected_at: "2026-08-28T11:00:00Z",
      },
      {
        ...item,
        id: "4",
        reference: "SBJ-X",
        status: "CANCELLED",
        cancelled_at: "2026-08-28T12:00:00Z",
      },
    ];
    listHistory.mockResolvedValue(states);
    render(<OperatorBookingHistory organizations={organizations} />);
    expect(await screen.findByText("SBJ-HISTORY")).toBeTruthy();
    expect(screen.getAllByText("Pending operator confirmation").length).toBe(2);
    expect(screen.getAllByText("Booking confirmed").length).toBe(2);
    expect(screen.getAllByText("Booking rejected").length).toBe(2);
    expect(screen.getAllByText("Booking cancelled").length).toBe(2);
    expect(screen.getAllByText(/EIDW → EGLF/).length).toBe(4);
    expect(
      screen.queryByText(/paid|settled|refunded|flight completed/i),
    ).toBeNull();
    expect(
      screen.queryByText(/customer|passport|provider|platform fee/i),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /confirm|reject|cancel/i }),
    ).toBeNull();
    expect(getBooking).not.toHaveBeenCalled();
  });

  it("uses authoritative status filtering, resets pagination and manually refreshes", async () => {
    listHistory.mockResolvedValue(
      Array.from({ length: 10 }, (_, index) => ({
        ...item,
        id: String(index),
      })),
    );
    render(<OperatorBookingHistory organizations={organizations} />);
    expect((await screen.findAllByText("SBJ-HISTORY")).length).toBe(10);
    expect(listHistory).toHaveBeenLastCalledWith(
      "org-a",
      { limit: 10, offset: 0, status: undefined },
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(listHistory).toHaveBeenLastCalledWith(
        "org-a",
        { limit: 10, offset: 10, status: undefined },
        expect.any(AbortSignal),
      ),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Booking status" }), {
      target: { value: "CONFIRMED" },
    });
    await waitFor(() =>
      expect(listHistory).toHaveBeenLastCalledWith(
        "org-a",
        { limit: 10, offset: 0, status: "CONFIRMED" },
        expect.any(AbortSignal),
      ),
    );
    const count = listHistory.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(listHistory).toHaveBeenCalledTimes(count + 1));
  });

  it("enforces monotonic epochs across A to B to A even when abort is ignored", async () => {
    let resolveFirstA!: (value: readonly OperatorBookingReadView[]) => void;
    let callsA = 0;
    listHistory.mockImplementation((organizationId: string) => {
      if (organizationId === "org-a" && callsA++ === 0)
        return new Promise((done) => (resolveFirstA = done));
      return Promise.resolve([
        {
          ...item,
          reference: organizationId === "org-a" ? "LATEST-A" : "CURRENT-B",
        },
      ]);
    });
    render(
      <OperatorBookingHistory
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN" },
          { id: "org-b", role: "OPERATOR_SALES" },
        ]}
      />,
    );
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(chooser, { target: { value: "org-a" } });
    await waitFor(() => expect(listHistory).toHaveBeenCalledTimes(1));
    fireEvent.change(chooser, { target: { value: "org-b" } });
    expect(await screen.findByText("CURRENT-B")).toBeTruthy();
    fireEvent.change(chooser, { target: { value: "org-a" } });
    expect(await screen.findByText("LATEST-A")).toBeTruthy();
    resolveFirstA([{ ...item, reference: "STALE-FIRST-A" }]);
    await waitFor(() => expect(screen.queryByText("STALE-FIRST-A")).toBeNull());
    expect(screen.getByText("LATEST-A")).toBeTruthy();
  });

  it("keeps only the latest epoch across rapid A to B to A to B resolution", async () => {
    const pending: Array<{
      organizationId: string;
      resolve: (value: readonly OperatorBookingReadView[]) => void;
    }> = [];
    listHistory.mockImplementation(
      (organizationId: string) =>
        new Promise<readonly OperatorBookingReadView[]>((resolve) =>
          pending.push({ organizationId, resolve }),
        ),
    );
    render(
      <OperatorBookingHistory
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN" },
          { id: "org-b", role: "OPERATOR_SALES" },
        ]}
      />,
    );
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    for (const [index, organizationId] of [
      "org-a",
      "org-b",
      "org-a",
      "org-b",
    ].entries()) {
      fireEvent.change(chooser, { target: { value: organizationId } });
      await waitFor(() => expect(listHistory).toHaveBeenCalledTimes(index + 1));
    }
    expect(pending.map(({ organizationId }) => organizationId)).toEqual([
      "org-a",
      "org-b",
      "org-a",
      "org-b",
    ]);
    pending[3].resolve([{ ...item, reference: "LATEST-B" }]);
    expect(await screen.findByText("LATEST-B")).toBeTruthy();
    pending[2].resolve([{ ...item, reference: "STALE-SECOND-A" }]);
    pending[0].resolve([{ ...item, reference: "STALE-FIRST-A" }]);
    pending[1].resolve([{ ...item, reference: "STALE-FIRST-B" }]);
    await waitFor(() => {
      expect(screen.queryByText(/STALE-/)).toBeNull();
      expect(screen.getByText("LATEST-B")).toBeTruthy();
    });
  });

  it.each([
    "OPERATOR_ADMIN",
    "OPERATOR_SALES",
    "OPERATOR_OPERATIONS",
    "OPERATOR_FINANCE",
    "OPERATOR_COMPLIANCE",
  ])("renders read-only history for %s", async (role) => {
    listHistory.mockResolvedValue([item]);
    render(<OperatorBookingHistory organizations={[{ id: "org-a", role }]} />);
    expect(await screen.findByText("SBJ-HISTORY")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /confirm|reject/i }),
    ).toBeNull();
  });

  it("opens only one explicit detail request and renders safe facts", async () => {
    getBooking.mockResolvedValue(item);
    render(
      <OperatorBookingHistory
        organizations={organizations}
        bookingId={item.id}
      />,
    );
    expect(screen.getByText("Loading booking detail…")).toBeTruthy();
    expect(await screen.findByText("SBJ-HISTORY")).toBeTruthy();
    expect(getBooking).toHaveBeenCalledTimes(1);
    expect(getBooking).toHaveBeenCalledWith(
      item.id,
      "org-a",
      expect.any(AbortSignal),
    );
    expect(listHistory).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "pending queue" })).toHaveAttribute(
      "href",
      "/operator/bookings",
    );
  });

  it("isolates safe detail 404 and generic read errors", async () => {
    getBooking.mockRejectedValueOnce(
      new ApiError(404, "not_found", "foreign secret", "client"),
    );
    const view = render(
      <OperatorBookingHistory
        organizations={organizations}
        bookingId={item.id}
      />,
    );
    expect(await screen.findByText("Booking not found")).toBeTruthy();
    expect(screen.queryByText("foreign secret")).toBeNull();
    view.unmount();
    getBooking.mockRejectedValueOnce(
      new ApiError(500, "internal", "provider secret", "server"),
    );
    render(
      <OperatorBookingHistory
        organizations={organizations}
        bookingId={item.id}
      />,
    );
    expect(
      await screen.findByText("Booking information could not be loaded"),
    ).toBeTruthy();
    expect(screen.queryByText("provider secret")).toBeNull();
  });

  it("discards late detail after an organization switch", async () => {
    let resolveA!: (value: OperatorBookingReadView) => void;
    getBooking.mockImplementation((_id: string, organizationId: string) =>
      organizationId === "org-a"
        ? new Promise((done) => (resolveA = done))
        : Promise.resolve({ ...item, reference: "DETAIL-B" }),
    );
    render(
      <OperatorBookingHistory
        bookingId={item.id}
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN" },
          { id: "org-b", role: "OPERATOR_FINANCE" },
        ]}
      />,
    );
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    fireEvent.change(chooser, { target: { value: "org-a" } });
    await waitFor(() => expect(getBooking).toHaveBeenCalledTimes(1));
    fireEvent.change(chooser, { target: { value: "org-b" } });
    expect(await screen.findByText("DETAIL-B")).toBeTruthy();
    resolveA({ ...item, reference: "STALE-DETAIL-A" });
    await waitFor(() =>
      expect(screen.queryByText("STALE-DETAIL-A")).toBeNull(),
    );
  });

  it("distinguishes old and new A detail epochs when abort is ignored", async () => {
    const pending: Array<{
      organizationId: string;
      resolve: (value: OperatorBookingReadView) => void;
    }> = [];
    getBooking.mockImplementation(
      (_id: string, organizationId: string) =>
        new Promise<OperatorBookingReadView>((resolve) =>
          pending.push({ organizationId, resolve }),
        ),
    );
    render(
      <OperatorBookingHistory
        bookingId={item.id}
        organizations={[
          { id: "org-a", role: "OPERATOR_ADMIN" },
          { id: "org-b", role: "OPERATOR_FINANCE" },
        ]}
      />,
    );
    const chooser = screen.getByRole("combobox", {
      name: "Operator organization",
    });
    for (const [index, organizationId] of [
      "org-a",
      "org-b",
      "org-a",
    ].entries()) {
      fireEvent.change(chooser, { target: { value: organizationId } });
      await waitFor(() => expect(getBooking).toHaveBeenCalledTimes(index + 1));
    }
    expect(pending.map(({ organizationId }) => organizationId)).toEqual([
      "org-a",
      "org-b",
      "org-a",
    ]);
    pending[2].resolve({ ...item, reference: "LATEST-DETAIL-A" });
    expect(await screen.findByText("LATEST-DETAIL-A")).toBeTruthy();
    pending[0].resolve({ ...item, reference: "STALE-FIRST-DETAIL-A" });
    pending[1].resolve({ ...item, reference: "STALE-DETAIL-B" });
    await waitFor(() => {
      expect(screen.queryByText(/STALE-/)).toBeNull();
      expect(screen.getByText("LATEST-DETAIL-A")).toBeTruthy();
    });
  });

  it("fails closed for an unknown future status", async () => {
    listHistory.mockResolvedValue([{ ...item, status: "FUTURE" }]);
    render(<OperatorBookingHistory organizations={organizations} />);
    expect(await screen.findByText("Status unavailable")).toBeTruthy();
    expect(screen.queryByText(/completed|paid|settled/i)).toBeNull();
  });
});
