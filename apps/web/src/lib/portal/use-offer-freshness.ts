"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import type { CustomerOffer } from "@/lib/api/types";

export const OFFER_REFRESH_INTERVAL_MS = 30_000;

type OfferReadState =
  | { readonly key: string; readonly status: "loading" }
  | { readonly key: string; readonly status: "error"; readonly error: ApiError }
  | {
      readonly key: string;
      readonly status: "ready";
      readonly data: readonly CustomerOffer[];
    };

function safeApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError(
        0,
        "unexpected_error",
        "An unexpected error occurred.",
        "server",
      );
}

export function useOfferFreshness(
  load: (signal: AbortSignal) => Promise<readonly CustomerOffer[]>,
  resourceKey: string,
  tripStatus: string,
) {
  const [state, setState] = useState<OfferReadState>({
    key: resourceKey,
    status: "loading",
  });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [activeKey, setActiveKey] = useState(resourceKey);
  const [visible, setVisible] = useState(
    () => typeof document === "undefined" || !document.hidden,
  );
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef<Promise<void> | null>(null);
  const generationRef = useRef(0);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  if (activeKey !== resourceKey) {
    setActiveKey(resourceKey);
    setState({ key: resourceKey, status: "loading" });
    setRefreshFailed(false);
  }

  const automaticEligible =
    tripStatus === "SUBMITTED" &&
    state.key === resourceKey &&
    state.status === "ready" &&
    !state.data.some((offer) => offer.status === "SELECTED");

  const refresh = useCallback(
    (background = true): Promise<void> => {
      if (inFlightRef.current) return inFlightRef.current;
      const generation = generationRef.current;
      const controller = new AbortController();
      controllerRef.current = controller;
      if (background) setRefreshing(true);
      const request = load(controller.signal)
        .then((data) => {
          if (
            !controller.signal.aborted &&
            generation === generationRef.current
          ) {
            setState({ key: resourceKey, status: "ready", data });
            setRefreshFailed(false);
          }
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted || generation !== generationRef.current)
            return;
          if (error instanceof DOMException && error.name === "AbortError")
            return;
          const current = stateRef.current;
          if (
            background &&
            current.key === resourceKey &&
            current.status === "ready"
          )
            setRefreshFailed(true);
          else
            setState({
              key: resourceKey,
              status: "error",
              error: safeApiError(error),
            });
        })
        .finally(() => {
          if (inFlightRef.current === request) inFlightRef.current = null;
          if (generation === generationRef.current) setRefreshing(false);
        });
      inFlightRef.current = request;
      return request;
    },
    [load, resourceKey],
  );

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    controllerRef.current?.abort();
    inFlightRef.current = null;
    queueMicrotask(() => {
      if (generation === generationRef.current) void refresh(false);
    });
    return () => {
      generationRef.current += 1;
      controllerRef.current?.abort();
      inFlightRef.current = null;
    };
  }, [resourceKey, refresh]);

  useEffect(() => {
    const onVisibilityChange = () => {
      const nextVisible = !document.hidden;
      setVisible(nextVisible);
      if (nextVisible && automaticEligible) void refresh();
    };
    const onFocus = () => {
      if (!document.hidden && automaticEligible) void refresh();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("focus", onFocus);
    };
  }, [automaticEligible, refresh]);

  useEffect(() => {
    if (!automaticEligible || !visible) return;
    const interval = window.setInterval(
      () => void refresh(),
      OFFER_REFRESH_INTERVAL_MS,
    );
    return () => window.clearInterval(interval);
  }, [automaticEligible, refresh, visible]);

  const replaceData = useCallback(
    (data: readonly CustomerOffer[]) => {
      setState({ key: resourceKey, status: "ready", data });
      setRefreshFailed(false);
    },
    [resourceKey],
  );

  const currentState: OfferReadState =
    state.key === resourceKey ? state : { key: resourceKey, status: "loading" };
  return {
    state: currentState,
    refreshing,
    refreshFailed,
    refresh,
    replaceData,
  };
}
