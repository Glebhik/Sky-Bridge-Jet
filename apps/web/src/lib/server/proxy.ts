import "server-only";

import {
  PROXY_ALLOWLIST,
  PROXY_PATTERN_ALLOWLIST,
  UPSTREAM_API_PREFIX,
  getUpstreamOrigin,
} from "@/lib/server/config";

/**
 * Core of the constrained same-origin API proxy (see ADR/architecture doc). Everything
 * here is server-only. The design goals:
 *
 * - the browser reaches only `/api/proxy/<path>` on the web origin;
 * - `<path>` must exactly match an entry in {@link PROXY_ALLOWLIST} (closed policy) — no
 *   arbitrary forwarding, no open-proxy, no user-controlled upstream host;
 * - path traversal / absolute / protocol-relative inputs are rejected;
 * - method, query string, request body, upstream status code and body, session cookies,
 *   and the CSRF header are preserved;
 * - server-only headers (and the upstream host) are never exposed to the browser, and
 *   cookies / tokens / authorization headers are never logged;
 * - authentication-sensitive responses are marked `no-store`;
 * - upstream unavailability yields a controlled typed error, and upstream 4xx/5xx status
 *   codes are preserved verbatim (never collapsed to 200).
 */

export const PROXY_BASE_PATH = "/api/proxy";

export type ProxyValidation =
  | {
      readonly ok: true;
      readonly path: string;
      readonly methods: readonly string[];
    }
  | { readonly ok: false; readonly status: number; readonly code: string };

/** A single unsafe path segment: empty, dot-segments, slashes, or encoded traversal. */
function isUnsafeSegment(segment: string): boolean {
  if (segment.length === 0 || segment === "." || segment === "..") return true;
  if (segment.includes("/") || segment.includes("\\")) return true;
  // Reject any percent-encoding: allow-list keys are literal, so encoded input can only
  // be an attempt to smuggle a separator or traversal.
  if (segment.includes("%")) return true;
  return false;
}

/** Canonical UUID (8-4-4-4-12 hex, case-insensitive). Used to bind `:uuid` path params. */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Match already-safe path segments against a single closed pattern. A literal pattern
 * segment must equal the request segment; a `":uuid"` segment must be a canonical UUID. The
 * segment counts must be identical, so no extra or missing segment is ever accepted. The
 * incoming segments have already passed {@link isUnsafeSegment}, so they cannot be empty,
 * encoded, dot-segments, or contain separators.
 */
function matchesPattern(
  segments: readonly string[],
  pattern: readonly string[],
): boolean {
  if (segments.length !== pattern.length) return false;
  return pattern.every((patternSegment, index) => {
    const segment = segments[index];
    if (patternSegment === ":uuid") return UUID_RE.test(segment);
    return patternSegment === segment;
  });
}

/**
 * Validate the incoming proxy path segments and method against the closed allow-list.
 * Returns the matched relative path and its permitted methods, or a typed rejection with
 * the status code the client should receive (404 unknown path, 405 method not allowed).
 *
 * Matching is closed and two-tier: an exact {@link PROXY_ALLOWLIST} entry first, then the
 * small {@link PROXY_PATTERN_ALLOWLIST} of `{id}` resource reads. It is never a prefix,
 * wildcard, or passthrough — an unmatched path is always 404, and a matched path still has
 * to permit the method (else 405).
 */
export function validateProxyRequest(
  segments: readonly string[],
  method: string,
): ProxyValidation {
  if (segments.length === 0 || segments.some(isUnsafeSegment)) {
    return { ok: false, status: 404, code: "not_found" };
  }
  const path = segments.join("/");
  const methods =
    PROXY_ALLOWLIST[path] ??
    PROXY_PATTERN_ALLOWLIST.find((pattern) =>
      matchesPattern(segments, pattern.segments),
    )?.methods;
  if (!methods) {
    return { ok: false, status: 404, code: "not_found" };
  }
  if (!methods.includes(method.toUpperCase())) {
    return { ok: false, status: 405, code: "method_not_allowed" };
  }
  return { ok: true, path, methods };
}

/**
 * Build the absolute upstream URL from the *trusted* origin, the fixed API prefix, the
 * already-validated allow-listed path, and the caller's original query string. The host
 * can never come from the request.
 */
export function buildUpstreamUrl(path: string, search: string): string {
  const origin = getUpstreamOrigin();
  const query = search && search !== "?" ? search : "";
  return `${origin}${UPSTREAM_API_PREFIX}/${path}${query}`;
}

// Request headers we forward upstream. A closed allow-list: the session cookie, the CSRF
// token, and content negotiation only. Never the browser `host`, and never anything else.
const FORWARDED_REQUEST_HEADERS: readonly string[] = [
  "cookie",
  "x-csrf-token",
  // The validated active-organization context for multi-organization customers. The API
  // still re-validates it against the principal's memberships (it is never trusted on its
  // own); forwarding it only lets the customer scope their own "my" reads.
  "x-organization-id",
  "content-type",
  "accept",
];

/** Build the upstream request headers from the incoming request (closed allow-list). */
export function buildUpstreamHeaders(incoming: Headers): Headers {
  const out = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value !== null) out.set(name, value);
  }
  return out;
}

// Response headers we relay to the browser. `set-cookie` is handled separately (multiple
// values). Hop-by-hop and server-only headers are intentionally dropped.
const FORWARDED_RESPONSE_HEADERS: readonly string[] = [
  "content-type",
  "location",
];

/**
 * Build the browser-facing response headers from the upstream response: the safe content
 * type, every `Set-Cookie` (so the session/CSRF cookies round-trip), and an explicit
 * `Cache-Control: no-store` so authenticated responses are never cached by a shared cache
 * or the browser.
 */
export function buildResponseHeaders(upstream: Response): Headers {
  const out = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) out.set(name, value);
  }
  // Undici exposes multiple Set-Cookie values via getSetCookie().
  const setCookie =
    typeof upstream.headers.getSetCookie === "function"
      ? upstream.headers.getSetCookie()
      : [];
  for (const cookie of setCookie) {
    out.append("set-cookie", cookie);
  }
  out.set("Cache-Control", "no-store");
  return out;
}

/** Rewrite only the local deterministic provider callback through the closed Web proxy. */
export function normalizePrivilegedAuthLocation(
  location: string | null,
): string | null {
  if (location === null) return null;
  const callback = `${UPSTREAM_API_PREFIX}/auth/platform/callback`;
  if (!location.startsWith(`${callback}?`)) return location;
  return `${PROXY_BASE_PATH}/auth/platform/callback${location.slice(callback.length)}`;
}

/** The controlled typed error returned when the upstream cannot be reached. */
export function upstreamUnavailableResponse(): Response {
  return new Response(
    JSON.stringify({
      error: {
        code: "upstream_unavailable",
        message: "The service is temporarily unavailable. Please try again.",
        details: null,
      },
    }),
    {
      status: 502,
      headers: {
        "content-type": "application/json",
        "Cache-Control": "no-store",
      },
    },
  );
}

/** The typed rejection body for a request the proxy refuses to forward. */
export function proxyRejectionResponse(status: number, code: string): Response {
  const message =
    status === 405
      ? "Method not allowed."
      : "The requested resource was not found.";
  return new Response(
    JSON.stringify({ error: { code, message, details: null } }),
    {
      status,
      headers: {
        "content-type": "application/json",
        "Cache-Control": "no-store",
      },
    },
  );
}

/**
 * Forward a validated request to the upstream API and adapt the response for the browser.
 * Body is streamed through unchanged for methods that carry one. The upstream status code
 * is preserved verbatim — 401/403/404/409/422/429/5xx all survive; nothing is turned into
 * a generic 200. No cookie, token, authorization header, or body is ever logged.
 */
export async function forwardToUpstream(
  request: Request,
  path: string,
): Promise<Response> {
  const url = buildUpstreamUrl(path, new URL(request.url).search);
  const method = request.method.toUpperCase();
  const hasBody = method !== "GET" && method !== "HEAD";
  const init: RequestInit = {
    method,
    headers: buildUpstreamHeaders(request.headers),
    redirect: "manual",
  };
  if (hasBody) {
    init.body = await request.text();
  }
  let upstream: Response;
  try {
    upstream = await fetch(url, init);
  } catch {
    // Network failure / DNS / connection refused: a controlled typed error, no leak.
    return upstreamUnavailableResponse();
  }
  let body = await upstream.text();
  if (upstream.ok && isOperatorOfferPath(path) && body.length > 0) {
    body = operatorSafeOfferBody(body);
  }
  const responseHeaders = buildResponseHeaders(upstream);
  const normalizedLocation = normalizePrivilegedAuthLocation(
    responseHeaders.get("location"),
  );
  if (normalizedLocation !== null) {
    responseHeaders.set("location", normalizedLocation);
  }
  return new Response(body.length > 0 ? body : null, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

function isOperatorOfferPath(path: string): boolean {
  return (
    path === "me/operator-offers" ||
    /^offers\/[0-9a-f-]+(?:\/(?:submit|withdraw))?$/i.test(path)
  );
}

/** Remove internal/commercial split fields before an Offer response reaches browser network. */
export function operatorSafeOfferBody(body: string): string {
  let value: unknown;
  try {
    value = JSON.parse(body) as unknown;
  } catch {
    return body;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return body;
  const source = value as Record<string, unknown>;
  const allowed = [
    "id",
    "trip_request_id",
    "aircraft_id",
    "status",
    "currency",
    "operator_amount_minor",
    "tax_amount_minor",
    "valid_until",
    "aircraft_registration",
    "aircraft_manufacturer",
    "aircraft_model",
    "aircraft_category",
    "operator_notes",
    "cancellation_policy",
    "included_services",
    "excluded_services",
    "created_at",
    "updated_at",
  ] as const;
  return JSON.stringify(
    Object.fromEntries(
      allowed.filter((key) => key in source).map((key) => [key, source[key]]),
    ),
  );
}
