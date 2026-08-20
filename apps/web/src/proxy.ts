import { NextResponse, type NextRequest } from "next/server";

import { LOGIN_PATH, sanitizeReturnPath } from "@/lib/auth/redirect";

/**
 * Portal route guard (first line), using Next.js's request `proxy` convention.
 *
 * For `/portal/*` requests without a session cookie it redirects to the login page,
 * preserving a *sanitized* same-origin return path. When a session cookie is present it
 * lets the request through — the protected layout then does the authoritative `/auth/me`
 * validation — and forwards the requested path so the layout can build the same safe return
 * redirect if that session turns out to be invalid.
 *
 * Cookie *presence* here is only a cheap redirect heuristic, never an authorization
 * decision: the backend remains the sole authority.
 */

const SESSION_COOKIE = "sbj_session";
const PATHNAME_HEADER = "x-portal-pathname";

export function proxy(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const target = `${pathname}${search}`;

  if (!request.cookies.has(SESSION_COOKIE)) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = LOGIN_PATH;
    loginUrl.search = "";
    loginUrl.searchParams.set("next", sanitizeReturnPath(target));
    return NextResponse.redirect(loginUrl);
  }

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(PATHNAME_HEADER, target);
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: ["/portal/:path*"],
};
