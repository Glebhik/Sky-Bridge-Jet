import type { MeResponse, Membership, User } from "@/lib/api/types";

/**
 * The canonical portal session model, shared by the server bootstrap and the client
 * provider. Frontend state is a *reflection* of the backend session — never an
 * authorization decision in its own right (the API re-checks every request).
 *
 * States:
 * - `loading` — the client has not yet resolved the backend session (client-only);
 * - `authenticated` — a live backend session; carries the user and derived customer orgs;
 * - `unauthenticated` — no/expired session (a 401 from the backend);
 * - `error` — a transient network/server failure; the user is NOT logged out.
 *
 * "Authenticated but without a usable customer context" is not a separate top-level state
 * but a property of `authenticated`: `customerOrganizations.length === 0`.
 */

export interface CustomerOrganization {
  readonly organizationId: string;
  readonly role: string;
}

export type SessionSnapshot =
  | { readonly status: "loading" }
  | {
      readonly status: "authenticated";
      readonly user: User;
      readonly memberships: readonly Membership[];
      readonly customerOrganizations: readonly CustomerOrganization[];
      readonly permissions: readonly string[];
    }
  | { readonly status: "unauthenticated" }
  | { readonly status: "error"; readonly transient: true };

/** Only CUSTOMER organizations are usable in the customer portal — never OPERATOR/PLATFORM. */
export function deriveCustomerOrganizations(
  memberships: readonly Membership[],
): CustomerOrganization[] {
  return memberships
    .filter((m) => m.organization_type === "CUSTOMER")
    .map((m) => ({ organizationId: m.organization_id, role: m.role }));
}

/** Build the authenticated snapshot from a `/auth/me` response. */
export function snapshotFromMe(me: MeResponse): SessionSnapshot {
  return {
    status: "authenticated",
    user: me.user,
    memberships: me.memberships,
    customerOrganizations: deriveCustomerOrganizations(me.memberships),
    permissions: me.permissions,
  };
}

export function isAuthenticated(
  snapshot: SessionSnapshot,
): snapshot is Extract<SessionSnapshot, { status: "authenticated" }> {
  return snapshot.status === "authenticated";
}

/** Whether an authenticated user has at least one usable customer organization. */
export function hasCustomerContext(snapshot: SessionSnapshot): boolean {
  return isAuthenticated(snapshot) && snapshot.customerOrganizations.length > 0;
}
