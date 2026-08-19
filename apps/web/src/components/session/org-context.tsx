"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  canSelectOrganization,
  resolveActiveOrganization,
} from "@/lib/org/model";
import type { CustomerOrganization } from "@/lib/session/model";
import { useSession } from "@/components/session/session-context";

/**
 * Active customer-organization context.
 *
 * The list of selectable organizations comes only from the authenticated backend session
 * (CUSTOMER memberships — never OPERATOR/PLATFORM). A stored preference is validated
 * against that list on every render and discarded if stale/unauthorized. Switching
 * organizations changes `activeOrganizationId`, which every organization-scoped consumer
 * keys its data on, so stale org-scoped data is invalidated on switch.
 *
 * The stored preference is read with `useSyncExternalStore` — SSR-safe (server snapshot is
 * null, so the first client render matches) and free of effect-driven state churn.
 */

const STORAGE_KEY = "sbj.activeOrganizationId";

interface OrganizationContextValue {
  readonly organizations: readonly CustomerOrganization[];
  readonly activeOrganizationId: string | null;
  readonly hasCustomerContext: boolean;
  readonly selectOrganization: (id: string) => void;
}

const OrganizationContext = createContext<OrganizationContextValue | null>(
  null,
);

function subscribeToStorage(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readStoredSnapshot(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage is a convenience only; never a source of authority.
  }
}

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const organizations = useMemo<readonly CustomerOrganization[]>(
    () =>
      session.status === "authenticated" ? session.customerOrganizations : [],
    [session],
  );

  // The persisted preference (cross-tab reactive, SSR-safe null on the server).
  const storedId = useSyncExternalStore(
    subscribeToStorage,
    readStoredSnapshot,
    () => null,
  );
  // An explicit in-session selection takes priority over the stored preference.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Resolve the active org from the authorized set: a valid selection/stored id is kept,
  // a stale one is discarded, and a single org auto-resolves.
  const { activeId } = resolveActiveOrganization(
    organizations,
    selectedId ?? storedId,
  );

  const selectOrganization = useCallback(
    (id: string) => {
      if (!canSelectOrganization(organizations, id)) return; // reject unauthorized ids
      setSelectedId(id);
      writeStored(id);
    },
    [organizations],
  );

  const value = useMemo<OrganizationContextValue>(
    () => ({
      organizations,
      activeOrganizationId: activeId,
      hasCustomerContext: activeId !== null,
      selectOrganization,
    }),
    [organizations, activeId, selectOrganization],
  );

  return (
    <OrganizationContext.Provider value={value}>
      {children}
    </OrganizationContext.Provider>
  );
}

export function useActiveOrganization(): OrganizationContextValue {
  const value = useContext(OrganizationContext);
  if (value === null) {
    throw new Error(
      "useActiveOrganization must be used within an OrganizationProvider.",
    );
  }
  return value;
}
