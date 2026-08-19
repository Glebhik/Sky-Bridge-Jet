import type { CustomerOrganization } from "@/lib/session/model";

/**
 * Pure active-organization resolution.
 *
 * The active organization is only ever chosen from the backend-authorized customer
 * organizations. A stored id (localStorage/state) is *never* trusted on its own: if it is
 * not present in the authorized list it is discarded as stale. Selection rules:
 *
 * - zero authorized customer orgs → no active organization (the "no usable customer
 *   context" state);
 * - a valid stored id → keep it;
 * - otherwise → auto-select the single org, or the first of several (deterministic) while
 *   the shell still offers a selector to switch.
 */
export interface ActiveOrganizationResolution {
  readonly activeId: string | null;
  /** True when a previously-stored id was rejected because it is no longer authorized. */
  readonly discardedStale: boolean;
}

export function resolveActiveOrganization(
  organizations: readonly CustomerOrganization[],
  storedId: string | null,
): ActiveOrganizationResolution {
  const authorized = new Set(organizations.map((o) => o.organizationId));
  if (storedId !== null && authorized.has(storedId)) {
    return { activeId: storedId, discardedStale: false };
  }
  const discardedStale = storedId !== null && !authorized.has(storedId);
  if (organizations.length === 0) {
    return { activeId: null, discardedStale };
  }
  return { activeId: organizations[0].organizationId, discardedStale };
}

/** Whether an id may be switched to — only if it is an authorized customer organization. */
export function canSelectOrganization(
  organizations: readonly CustomerOrganization[],
  id: string,
): boolean {
  return organizations.some((o) => o.organizationId === id);
}
