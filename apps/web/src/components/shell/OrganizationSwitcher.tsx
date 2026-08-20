"use client";

import { useId } from "react";

import { useActiveOrganization } from "@/components/session/org-context";

/**
 * Presents the active customer organization. With a single organization it is shown
 * read-only; with several it becomes a labelled `<select>` that switches the active
 * organization (only among backend-authorized ones). With none it renders nothing — the
 * shell shows the "no customer context" notice instead.
 */
export function OrganizationSwitcher() {
  const { organizations, activeOrganizationId, selectOrganization } =
    useActiveOrganization();
  const selectId = useId();

  if (organizations.length === 0) return null;

  if (organizations.length === 1) {
    return (
      <div className="org-switcher">
        <span className="org-switcher__label">Organization</span>
        <span className="org-switcher__value">
          {organizationLabel(organizations[0].organizationId)}
        </span>
      </div>
    );
  }

  return (
    <div className="org-switcher">
      <label className="org-switcher__label" htmlFor={selectId}>
        Organization
      </label>
      <select
        id={selectId}
        className="org-switcher__select"
        value={activeOrganizationId ?? ""}
        onChange={(event) => selectOrganization(event.target.value)}
      >
        {organizations.map((org) => (
          <option key={org.organizationId} value={org.organizationId}>
            {organizationLabel(org.organizationId)}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * A stable, human-readable short label for an organization id. Organization display names
 * are not part of the Phase 9.1.A `/auth/me` contract, so the shell shows a short id token
 * rather than inventing a name; the profile/name experience is a later phase.
 */
function organizationLabel(organizationId: string): string {
  return `Account ${organizationId.slice(0, 8)}`;
}
