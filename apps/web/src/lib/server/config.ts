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
 * used as a general-purpose or open proxy. Only the customer-portal-shell surface for
 * Phase 9.1.B is included (session, login/logout, explicit account recovery, and the
 * customer "my" reads that back the shell's honest empty/loading states).
 */
export const PROXY_ALLOWLIST: Readonly<Record<string, readonly string[]>> = {
  "auth/me": ["GET"],
  "auth/login": ["POST"],
  "auth/logout": ["POST"],
  "auth/logout-all": ["POST"],
  "auth/customer-account/recover": ["POST"],
  "me/trip-requests": ["GET"],
  "me/bookings": ["GET"],
  "me/payments": ["GET"],
};

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
