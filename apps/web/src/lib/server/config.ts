import "server-only";

/**
 * Server-only upstream configuration for the same-origin API proxy.
 *
 * The browser never learns or supplies the upstream API origin: it talks only to the
 * web application's own origin (`/api/proxy/...`). The upstream origin is read here,
 * server-side, from a NON-public environment variable (`API_UPSTREAM_ORIGIN`) — never a
 * `NEXT_PUBLIC_*` value — so it is impossible to expose it to client bundles or to let a
 * request override the host. `import "server-only"` makes a client-side import a build
 * error.
 */

const DEFAULT_UPSTREAM_ORIGIN = "http://localhost:8000";

/** The upstream API version prefix. Every proxied path is scoped under it. */
export const UPSTREAM_API_PREFIX = "/api/v1";

/**
 * The explicit allow-list of upstream API paths the portal proxy may reach, keyed by the
 * path *relative to* {@link UPSTREAM_API_PREFIX} and the HTTP methods permitted for each.
 * This is a closed policy — anything not listed is rejected — so the proxy can never be
 * used as a general-purpose or open proxy. It carries the customer-portal-shell surface
 * from Phase 9.1.B (session, login/logout, explicit account recovery, and the customer
 * "my" reads) plus the Phase 9.2.A public account-entry contracts (register, verify,
 * verification resend, and password-reset request/confirm). Every entry is an exact path;
 * there is no `auth/*` wildcard and no dynamic passthrough.
 *
 * Phase 9.3.B adds exactly three customer *mutation* entries — creating a passenger, creating
 * a DRAFT trip request, and (as a parameterized entry below) submitting that same DRAFT — plus
 * the `airports` *collection* read the airport picker needs. The authoritative customer is
 * still derived server-side from the authenticated principal + validated active organization;
 * the browser never sends `customer_id`. Phase 9.3.C adds cancellation below, and Phase
 * 9.4.A adds only the customer-safe trip-scoped published-offer GET described below.
 */
export const PROXY_ALLOWLIST: Readonly<Record<string, readonly string[]>> = {
  "auth/me": ["GET"],
  "auth/register": ["POST"],
  "auth/verify-email": ["POST"],
  "auth/verification/resend": ["POST"],
  "auth/login": ["POST"],
  "auth/logout": ["POST"],
  "auth/logout-all": ["POST"],
  "auth/password-reset": ["POST"],
  "auth/password-reset/confirm": ["POST"],
  "auth/customer-account/recover": ["POST"],
  "me/trip-requests": ["GET"],
  "me/bookings": ["GET"],
  "me/payments": ["GET"],
  "me/operator-bookings": ["GET"],
  "me/operator-opportunities": ["GET"],
  "me/operator-aircraft": ["GET"],
  "me/operator-offers": ["POST"],
  // Phase 9.3.B customer write journey (create DRAFT → submit same DRAFT). Exact paths only.
  passengers: ["POST"],
  "trip-requests": ["POST"],
  // Phase 9.5.A: create one customer Booking from an already-selected offer.
  bookings: ["POST"],
  // Public airport reference collection used by the origin/destination picker (read only).
  airports: ["GET"],
};

/**
 * A single closed, parameterized allow-list entry. `segments` is matched against the
 * request path one segment at a time: a literal segment must match exactly, and the
 * `":uuid"` placeholder matches exactly one path segment that is a canonical UUID (never an
 * empty, encoded, or multi-segment value — those are already rejected upstream in the
 * proxy's per-segment safety check). The segment count must match exactly, so no extra or
 * missing segment is ever accepted. This is NOT prefix matching, a wildcard, or a
 * passthrough: it only reaches the specific customer resource-by-id reads named below.
 */
export interface ProxyPattern {
  readonly segments: readonly string[];
  readonly methods: readonly string[];
}

/**
 * Closed parameterized routes for the Phase 9.3 customer portal. The customer's own
 * trip-request detail (`GET /trip-requests/{id}`) and the public airport lookups used to
 * render its legs (`GET /airports/{id}`) both live behind an `{id}` path parameter that the
 * exact-string {@link PROXY_ALLOWLIST} cannot express. Each `{id}` must be a UUID.
 *
 * Phase 9.3.B added the submit mutation; Phase 9.3.C added exactly one more: cancelling the
 * customer's own trip request (`POST /trip-requests/{id}/cancel`). Both are three-segment
 * patterns with a literal trailing verb. Phase 9.4.A exposes only customer-safe, trip-scoped
 * published offer reads through `GET /trip-requests/{id}/offers`. Offer selection, operator
 * Phase 9.4.B adds the one exact customer selection mutation; all other offer mutations,
 * booking mutations, and payment mutations remain unexposed. This is NOT
 * prefix matching, a wildcard, or a passthrough; the segment count must match exactly, and
 * each route is bound to exactly its listed method.
 */
export const PROXY_PATTERN_ALLOWLIST: readonly ProxyPattern[] = [
  { segments: ["trip-requests", ":uuid"], methods: ["GET"] },
  { segments: ["trip-requests", ":uuid", "offers"], methods: ["GET"] },
  // Authoritative duplicate/network-ambiguity recovery; customer-safe response only.
  { segments: ["trip-requests", ":uuid", "booking"], methods: ["GET"] },
  {
    segments: ["trip-requests", ":uuid", "offers", ":uuid", "select"],
    methods: ["POST"],
  },
  { segments: ["trip-requests", ":uuid", "submit"], methods: ["POST"] },
  { segments: ["trip-requests", ":uuid", "cancel"], methods: ["POST"] },
  { segments: ["airports", ":uuid"], methods: ["GET"] },
  { segments: ["bookings", ":uuid", "confirm"], methods: ["POST"] },
  { segments: ["bookings", ":uuid", "reject"], methods: ["POST"] },
  { segments: ["offers", ":uuid"], methods: ["GET", "PATCH"] },
  { segments: ["offers", ":uuid", "submit"], methods: ["POST"] },
  { segments: ["offers", ":uuid", "withdraw"], methods: ["POST"] },
  {
    segments: ["bookings", ":uuid", "payment", "initiate"],
    methods: ["POST"],
  },
];

/**
 * Resolve the trusted upstream API origin (scheme + host + optional port only). Throws if
 * the configured value is not an absolute http(s) origin, so a misconfiguration fails
 * closed at request time rather than silently forwarding somewhere unexpected.
 */
export function getUpstreamOrigin(): string {
  const configured = process.env.API_UPSTREAM_ORIGIN ?? DEFAULT_UPSTREAM_ORIGIN;
  let url: URL;
  try {
    url = new URL(configured);
  } catch {
    throw new Error("API_UPSTREAM_ORIGIN must be an absolute URL.");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("API_UPSTREAM_ORIGIN must use http or https.");
  }
  // Deliberately discard any path/query/hash: only the origin is trusted.
  return url.origin;
}
