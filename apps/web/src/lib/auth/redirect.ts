/**
 * Safe return-path handling for the login redirect.
 *
 * A `next` parameter is only ever allowed to be a **same-origin, absolute path** (starts
 * with a single `/`, not `//`, no scheme, no backslash, no control characters). Absolute
 * URLs, protocol-relative URLs (`//evil.com`), external hosts, and malformed values are
 * rejected and fall back to the default. This prevents open-redirect abuse while still
 * letting a user return to the page they were trying to reach.
 */

const DEFAULT_RETURN_PATH = "/portal";
export const LOGIN_PATH = "/login";
const RETURN_PARAM = "next";

/** True if the string contains any ASCII control character (incl. CR/LF, tab, NUL, DEL). */
function hasControlCharacter(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code <= 0x1f || code === 0x7f) return true;
  }
  return false;
}

/** Normalize an untrusted `next` value to a safe same-origin path, or the default. */
export function sanitizeReturnPath(
  next: string | null | undefined,
  fallback: string = DEFAULT_RETURN_PATH,
): string {
  if (typeof next !== "string" || next.length === 0) return fallback;
  // Must be an absolute path, but not protocol-relative (`//host`) or a backslash trick.
  if (
    !next.startsWith("/") ||
    next.startsWith("//") ||
    next.startsWith("/\\")
  ) {
    return fallback;
  }
  // Reject backslashes and control characters (e.g. CR/LF header-injection attempts).
  if (next.includes("\\") || hasControlCharacter(next)) return fallback;
  // Reject anything that parses as having a scheme or a different authority component.
  try {
    const url = new URL(next, "http://portal.local");
    if (url.origin !== "http://portal.local") return fallback;
    // Never allow returning to the login page itself (avoids redirect loops).
    if (url.pathname === LOGIN_PATH) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}

/** Build the login URL that remembers a safe return path. */
export function buildLoginRedirect(currentPath: string): string {
  const safe = sanitizeReturnPath(currentPath);
  const params = new URLSearchParams({ [RETURN_PARAM]: safe });
  return `${LOGIN_PATH}?${params.toString()}`;
}

/** Read and sanitize the return path from URL search params. */
export function returnPathFromSearch(
  search: URLSearchParams,
  fallback: string = DEFAULT_RETURN_PATH,
): string {
  return sanitizeReturnPath(search.get(RETURN_PARAM), fallback);
}
