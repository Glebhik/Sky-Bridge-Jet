"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import type { CustomerBooking } from "@/lib/api/types";

export const BOOKING_REFRESH_INTERVAL_MS = 30_000;
export const BOOKING_REFRESH_WARNING = "Booking status could not be refreshed.";

export function hasPendingBooking(
  bookings: readonly CustomerBooking[],
): boolean {
  return bookings.some(
    (booking) => booking.status === "PENDING_OPERATOR_CONFIRMATION",
  );
}

type BookingFreshnessState =
  | { readonly key: string; readonly status: "loading" }
  | { readonly key: string; readonly status: "error"; readonly error: ApiError }
  | {
      readonly key: string;
      readonly status: "ready";
      readonly data: readonly CustomerBooking[];
      readonly refreshing: boolean;
      readonly warning: string | null;
    };

type RefreshReason = "initial" | "automatic" | "manual";

/**
 * Owns the bounded freshness lifecycle for the currently visible customer Booking list.
 * There is one list GET in flight at a time, one timer for the whole list, and no polling
 * once the list has no known Pending Booking. Identity and generation checks complement
 * AbortController so an obsolete organization response can never commit.
 */
export function useBookingFreshness(
  load: (signal: AbortSignal) => Promise<readonly CustomerBooking[]>,
  resourceKey: string,
  enabled: boolean,
): {
  readonly state: BookingFreshnessState;
  readonly refresh: () => Promise<void>;
} {
  const [state, setState] = useState<BookingFreshnessState>({
    key: resourceKey,
    status: "loading",
  });
  const identityRef = useRef(resourceKey);
  const refreshRef = useRef<() => Promise<void>>(async () => undefined);

  useEffect(() => {
    if (!enabled) return;

    const identity = resourceKey;
    identityRef.current = identity;
    let generation = 0;
    let disposed = false;
    let latest: readonly CustomerBooking[] | null = null;
    let inFlight: Promise<void> | null = null;
    let activeController: AbortController | null = null;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const isCurrent = (requestGeneration: number) =>
      !disposed &&
      identityRef.current === identity &&
      requestGeneration === generation;

    const stopInterval = () => {
      if (intervalId !== null) clearInterval(intervalId);
      intervalId = null;
    };

    const isEligible = () => latest !== null && hasPendingBooking(latest);

    const request = (reason: RefreshReason): Promise<void> => {
      if (inFlight !== null) return inFlight;

      const requestGeneration = ++generation;
      const controller = new AbortController();
      activeController = controller;
      if (reason !== "initial") {
        setState((current) =>
          current.status === "ready"
            ? { ...current, refreshing: true }
            : current,
        );
      }

      const operation = load(controller.signal)
        .then((data) => {
          if (!isCurrent(requestGeneration)) return;
          latest = data;
          setState({
            key: identity,
            status: "ready",
            data,
            refreshing: false,
            warning: null,
          });
          if (!hasPendingBooking(data)) stopInterval();
        })
        .catch((error: unknown) => {
          if (!isCurrent(requestGeneration) || controller.signal.aborted)
            return;
          if (error instanceof DOMException && error.name === "AbortError")
            return;
          if (reason === "initial" || latest === null) {
            setState({
              key: identity,
              status: "error",
              error:
                error instanceof ApiError
                  ? error
                  : new ApiError(
                      0,
                      "unexpected_error",
                      "An unexpected error occurred.",
                      "server",
                    ),
            });
            return;
          }
          setState((current) =>
            current.status === "ready"
              ? {
                  ...current,
                  refreshing: false,
                  warning: BOOKING_REFRESH_WARNING,
                }
              : current,
          );
        })
        .finally(() => {
          if (inFlight === operation) inFlight = null;
          if (activeController === controller) activeController = null;
        });
      inFlight = operation;
      return operation;
    };

    const startInterval = () => {
      stopInterval();
      if (!isEligible() || document.visibilityState === "hidden") return;
      intervalId = setInterval(() => {
        void request("automatic");
      }, BOOKING_REFRESH_INTERVAL_MS);
    };

    const refreshAndRestoreCadence = () => {
      if (!isEligible()) return;
      void request("automatic").finally(startInterval);
    };

    const onFocus = () => {
      if (document.visibilityState !== "hidden" && isEligible()) {
        void request("automatic");
      }
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        stopInterval();
      } else {
        refreshAndRestoreCadence();
      }
    };

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);
    refreshRef.current = () => request("manual");
    void request("initial").then(startInterval);

    return () => {
      disposed = true;
      generation += 1;
      stopInterval();
      activeController?.abort();
      inFlight = null;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      refreshRef.current = async () => undefined;
    };
  }, [enabled, load, resourceKey]);

  const refresh = useCallback(() => refreshRef.current(), []);
  return {
    state:
      state.key === resourceKey
        ? state
        : { key: resourceKey, status: "loading" },
    refresh,
  };
}
