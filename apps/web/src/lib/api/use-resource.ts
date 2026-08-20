"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/errors";

/**
 * A small client hook for loading a portal API resource with honest states: `loading`,
 * `ready` (with data), or `error` (a typed {@link ApiError}). The request is aborted on
 * unmount or when `resourceKey` changes (e.g. an organization switch), so stale
 * organization-scoped data never lands after a switch. When the key changes the state is
 * reset to `loading` during render (React's "adjust state on prop change" pattern), so no
 * stale data is shown for the new key.
 */
export type ResourceState<T> =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "error"; readonly error: ApiError };

export function useApiResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  resourceKey: string,
): ResourceState<T> {
  const [state, setState] = useState<ResourceState<T>>({ status: "loading" });
  const [activeKey, setActiveKey] = useState(resourceKey);

  if (activeKey !== resourceKey) {
    // The resource identity changed (e.g. organization switch): drop stale data now.
    setActiveKey(resourceKey);
    setState({ status: "loading" });
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError(
                0,
                "unexpected_error",
                "An unexpected error occurred.",
                "server",
              );
        setState({ status: "error", error: apiError });
      });
    return () => controller.abort();
    // `load` is recreated per render; the effect is intentionally keyed on resourceKey only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceKey]);

  return state;
}
