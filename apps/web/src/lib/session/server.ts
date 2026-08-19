import "server-only";

import { cookies } from "next/headers";

import type { MeResponse } from "@/lib/api/types";
import { UPSTREAM_API_PREFIX, getUpstreamOrigin } from "@/lib/server/config";
import { snapshotFromMe, type SessionSnapshot } from "@/lib/session/model";

/**
 * Resolve the backend session on the server, for the protected layout boundary. It reads
 * the incoming request cookies and calls the upstream `/auth/me` directly (server→server,
 * not through the browser proxy), forwarding only the cookie header. A reload/refresh
 * always runs this — the session is re-validated against the backend every time, never
 * trusted from client storage.
 *
 * - 200 → authenticated snapshot (with derived customer organizations);
 * - 401 → unauthenticated;
 * - anything else / network failure → transient error (the user is NOT logged out).
 */
export async function getServerSession(): Promise<SessionSnapshot> {
  const cookieHeader = (await cookies()).toString();
  if (cookieHeader.length === 0) {
    return { status: "unauthenticated" };
  }

  let response: Response;
  try {
    response = await fetch(
      `${getUpstreamOrigin()}${UPSTREAM_API_PREFIX}/auth/me`,
      {
        method: "GET",
        headers: { cookie: cookieHeader, accept: "application/json" },
        cache: "no-store",
        redirect: "manual",
      },
    );
  } catch {
    return { status: "error", transient: true };
  }

  if (response.status === 401) {
    return { status: "unauthenticated" };
  }
  if (!response.ok) {
    return { status: "error", transient: true };
  }
  try {
    const me = (await response.json()) as MeResponse;
    return snapshotFromMe(me);
  } catch {
    return { status: "error", transient: true };
  }
}
