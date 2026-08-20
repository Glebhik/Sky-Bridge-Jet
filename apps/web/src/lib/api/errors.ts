import type { ApiErrorBody } from "@/lib/api/types";

/**
 * A typed API error. Every non-2xx response the typed client sees becomes an `ApiError`,
 * preserving the upstream HTTP `status` and the safe envelope `code`/`message` so callers
 * can branch on them (401 vs 403 vs 409 vs 429 vs 5xx) without string-matching.
 *
 * `kind` classifies the failure for UI decisions without inspecting the status everywhere:
 * - `auth` (401): the session is missing/expired — treat as unauthenticated;
 * - `forbidden` (403): authenticated but not permitted — distinct from `auth`;
 * - `conflict` (409): a safe state conflict (e.g. already provisioned);
 * - `rate_limited` (429);
 * - `client` (other 4xx);
 * - `server` (5xx or the proxy's upstream-unavailable);
 * - `network` (the request never produced a response);
 * - `malformed` (a response that could not be parsed as expected).
 */
export type ApiErrorKind =
  | "auth"
  | "forbidden"
  | "conflict"
  | "rate_limited"
  | "client"
  | "server"
  | "network"
  | "malformed";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly kind: ApiErrorKind;

  constructor(
    status: number,
    code: string,
    message: string,
    kind: ApiErrorKind,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.kind = kind;
  }

  get isUnauthenticated(): boolean {
    return this.kind === "auth";
  }

  get isForbidden(): boolean {
    return this.kind === "forbidden";
  }

  /** Transient failures a caller may retry / must not treat as a logout. */
  get isTransient(): boolean {
    return this.kind === "server" || this.kind === "network";
  }
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "client";
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

/** Build an {@link ApiError} from a non-OK response and its (already-read) parsed body. */
export function apiErrorFromResponse(
  status: number,
  parsed: unknown,
): ApiError {
  const kind = kindForStatus(status);
  if (isApiErrorBody(parsed)) {
    return new ApiError(status, parsed.error.code, parsed.error.message, kind);
  }
  return new ApiError(
    status,
    "unexpected_error",
    "An unexpected error occurred.",
    kind,
  );
}
