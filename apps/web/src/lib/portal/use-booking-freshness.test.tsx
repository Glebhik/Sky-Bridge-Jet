import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomerBooking } from "@/lib/api/types";
import {
  BOOKING_REFRESH_INTERVAL_MS,
  BOOKING_REFRESH_WARNING,
  hasPendingBooking,
  useBookingFreshness,
} from "@/lib/portal/use-booking-freshness";

const makeBooking = (
  status: CustomerBooking["status"] | string,
): CustomerBooking =>
  ({
    id: "booking",
    reference: "SBJ-BOOKING",
    trip_request_id: "trip",
    operator_offer_id: "offer",
    status,
    currency: "EUR",
    total_amount_minor: 123456,
    tax_amount_minor: 1000,
    operator_legal_name: "Operator",
    aircraft_registration: "EI-ONE",
    aircraft_manufacturer: "Bombardier",
    aircraft_model: "Global 7500",
    aircraft_category: "ULTRA_LONG_RANGE",
    confirmed_at: status === "CONFIRMED" ? "2026-08-26T10:00:00Z" : null,
    cancelled_at: status === "CANCELLED" ? "2026-08-26T10:00:00Z" : null,
    cancellation_actor: null,
    cancellation_reason: null,
    created_at: "2026-08-26T09:00:00Z",
    updated_at: "2026-08-26T10:00:00Z",
  }) as CustomerBooking;

let visibility: DocumentVisibilityState;

function setVisibility(next: DocumentVisibilityState) {
  visibility = next;
  document.dispatchEvent(new Event("visibilitychange"));
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useBookingFreshness", () => {
  it("fails closed for terminal and unknown statuses", () => {
    expect(hasPendingBooking([makeBooking("CONFIRMED")])).toBe(false);
    expect(hasPendingBooking([makeBooking("REJECTED")])).toBe(false);
    expect(hasPendingBooking([makeBooking("CANCELLED")])).toBe(false);
    expect(hasPendingBooking([makeBooking("FUTURE")])).toBe(false);
    expect(
      hasPendingBooking([makeBooking("PENDING_OPERATOR_CONFIRMATION")]),
    ).toBe(true);
  });

  it("performs one list GET at exactly 30 seconds without timer multiplication", async () => {
    const load = vi
      .fn()
      .mockResolvedValue([makeBooking("PENDING_OPERATOR_CONFIRMATION")]);
    renderHook(() => useBookingFreshness(load, "org-a", true));
    await flush();
    expect(load).toHaveBeenCalledTimes(1);

    await act(async () => vi.advanceTimersByTimeAsync(29_999));
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("pauses while hidden, refreshes once on visibility, and restores cadence", async () => {
    const load = vi
      .fn()
      .mockResolvedValue([makeBooking("PENDING_OPERATOR_CONFIRMATION")]);
    renderHook(() => useBookingFreshness(load, "org-a", true));
    await flush();

    act(() => setVisibility("hidden"));
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(load).toHaveBeenCalledTimes(1);
    act(() => setVisibility("visible"));
    await flush();
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("refreshes once on focus only while Pending and enabled", async () => {
    const pendingLoad = vi
      .fn()
      .mockResolvedValue([makeBooking("PENDING_OPERATOR_CONFIRMATION")]);
    const pending = renderHook(() =>
      useBookingFreshness(pendingLoad, "org-a", true),
    );
    await flush();
    act(() => window.dispatchEvent(new Event("focus")));
    await flush();
    expect(pendingLoad).toHaveBeenCalledTimes(2);
    pending.unmount();

    const terminalLoad = vi.fn().mockResolvedValue([makeBooking("CONFIRMED")]);
    const terminal = renderHook(() =>
      useBookingFreshness(terminalLoad, "org-b", true),
    );
    await flush();
    act(() => window.dispatchEvent(new Event("focus")));
    await flush();
    expect(terminalLoad).toHaveBeenCalledTimes(1);
    terminal.unmount();

    const disabledLoad = vi.fn();
    renderHook(() => useBookingFreshness(disabledLoad, "none", false));
    act(() => window.dispatchEvent(new Event("focus")));
    expect(disabledLoad).not.toHaveBeenCalled();
  });

  it("deduplicates manual, interval, focus, and visibility triggers", async () => {
    let resolveRefresh!: (bookings: readonly CustomerBooking[]) => void;
    const load = vi
      .fn()
      .mockResolvedValueOnce([makeBooking("PENDING_OPERATOR_CONFIRMATION")])
      .mockReturnValueOnce(
        new Promise<readonly CustomerBooking[]>((resolve) => {
          resolveRefresh = resolve;
        }),
      )
      .mockResolvedValue([makeBooking("PENDING_OPERATOR_CONFIRMATION")]);
    const { result } = renderHook(() =>
      useBookingFreshness(load, "org-a", true),
    );
    await flush();

    void result.current.refresh();
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    act(() => window.dispatchEvent(new Event("focus")));
    void result.current.refresh();
    act(() => setVisibility("hidden"));
    act(() => setVisibility("visible"));
    expect(load).toHaveBeenCalledTimes(2);

    resolveRefresh([makeBooking("PENDING_OPERATOR_CONFIRMATION")]);
    await flush();
    act(() => window.dispatchEvent(new Event("focus")));
    await flush();
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("aborts identity A and rejects its late stale response after B wins", async () => {
    let resolveA!: (bookings: readonly CustomerBooking[]) => void;
    let signalA!: AbortSignal;
    const loadA = vi.fn(
      (signal: AbortSignal) =>
        new Promise<readonly CustomerBooking[]>((resolve) => {
          expect(signal.aborted).toBe(false);
          signalA = signal;
          resolveA = resolve;
        }),
    );
    const loadB = vi.fn().mockResolvedValue([makeBooking("CONFIRMED")]);
    const { result, rerender } = renderHook(
      ({ organization }: { organization: "a" | "b" }) =>
        useBookingFreshness(
          organization === "a" ? loadA : loadB,
          organization,
          true,
        ),
      { initialProps: { organization: "a" as "a" | "b" } },
    );

    rerender({ organization: "b" });
    await flush();
    expect(signalA.aborted).toBe(true);
    expect(loadB).toHaveBeenCalledTimes(1);
    expect(result.current.state).toMatchObject({
      status: "ready",
      data: [{ status: "CONFIRMED" }],
    });

    resolveA([makeBooking("PENDING_OPERATOR_CONFIRMATION")]);
    await flush();
    expect(result.current.state).toMatchObject({
      status: "ready",
      data: [{ status: "CONFIRMED" }],
    });
  });

  it("retains known data on repeated failures and clears one stable warning on success", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce([makeBooking("PENDING_OPERATOR_CONFIRMATION")])
      .mockRejectedValueOnce(new Error("raw backend trace"))
      .mockRejectedValueOnce(new Error("raw backend trace"))
      .mockResolvedValueOnce([makeBooking("REJECTED")]);
    const { result } = renderHook(() =>
      useBookingFreshness(load, "org-a", true),
    );
    await flush();

    await act(async () => result.current.refresh());
    expect(result.current.state).toMatchObject({
      status: "ready",
      data: [{ status: "PENDING_OPERATOR_CONFIRMATION" }],
      warning: BOOKING_REFRESH_WARNING,
    });
    const warning =
      result.current.state.status === "ready"
        ? result.current.state.warning
        : null;
    await act(async () => result.current.refresh());
    expect(
      result.current.state.status === "ready"
        ? result.current.state.warning
        : null,
    ).toBe(warning);

    await act(async () => result.current.refresh());
    expect(result.current.state).toMatchObject({
      status: "ready",
      data: [{ status: "REJECTED" }],
      warning: null,
    });
  });

  it.each(["CONFIRMED", "REJECTED", "CANCELLED"] as const)(
    "stops automatic and focus freshness after transition to %s",
    async (status) => {
      const load = vi
        .fn()
        .mockResolvedValueOnce([makeBooking("PENDING_OPERATOR_CONFIRMATION")])
        .mockResolvedValueOnce([makeBooking(status)]);
      renderHook(() => useBookingFreshness(load, "org-a", true));
      await flush();
      await act(async () =>
        vi.advanceTimersByTimeAsync(BOOKING_REFRESH_INTERVAL_MS),
      );
      expect(load).toHaveBeenCalledTimes(2);
      act(() => window.dispatchEvent(new Event("focus")));
      await act(async () =>
        vi.advanceTimersByTimeAsync(BOOKING_REFRESH_INTERVAL_MS * 2),
      );
      expect(load).toHaveBeenCalledTimes(2);
    },
  );
});
