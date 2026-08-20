"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { snapshotFromMe, type SessionSnapshot } from "@/lib/session/model";

/**
 * The single canonical client session context. It is seeded with the server-resolved
 * snapshot (so the first paint already reflects the backend session — no protected-data
 * flash) and can re-validate against the backend on demand.
 *
 * Authorization is never inferred from this state: components use it to decide what to
 * render, but every API call is independently authorized by the backend. A transient
 * refresh failure keeps the existing snapshot — it never silently logs the user out.
 */

interface SessionContextValue {
  readonly session: SessionSnapshot;
  /** Re-fetch `/auth/me`; 401 → unauthenticated, transient failure → keep current state. */
  readonly refresh: () => Promise<void>;
  /** End the backend session, then reflect unauthenticated locally. */
  readonly logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  initialSession,
  children,
}: {
  initialSession: SessionSnapshot;
  children: ReactNode;
}) {
  const [session, setSession] = useState<SessionSnapshot>(initialSession);

  const refresh = useCallback(async () => {
    try {
      const me = await portalApi.getMe();
      setSession(snapshotFromMe(me));
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthenticated) {
        setSession({ status: "unauthenticated" });
        return;
      }
      // Transient network/server error: do not log the user out; keep the last snapshot.
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await portalApi.logout();
    } catch {
      // Even if the call fails, reflect unauthenticated locally; the cookie may persist
      // server-side but the UI stops treating the user as signed in.
    }
    setSession({ status: "unauthenticated" });
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({ session, refresh, logout }),
    [session, refresh, logout],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession must be used within a SessionProvider.");
  }
  return value;
}
