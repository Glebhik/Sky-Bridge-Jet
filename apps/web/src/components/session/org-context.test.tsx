import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  OrganizationProvider,
  useActiveOrganization,
} from "@/components/session/org-context";
import { SessionProvider } from "@/components/session/session-context";
import type { SessionSnapshot } from "@/lib/session/model";

function authenticatedWith(orgIds: string[]): SessionSnapshot {
  return {
    status: "authenticated",
    user: {
      id: "u1",
      email: "a@b.co",
      display_name: null,
      status: "ACTIVE",
      email_verified_at: null,
      created_at: "2026-01-01T00:00:00Z",
    },
    memberships: orgIds.map((id) => ({
      organization_id: id,
      organization_type: "CUSTOMER" as const,
      role: "CUSTOMER_OWNER",
    })),
    customerOrganizations: orgIds.map((id) => ({
      organizationId: id,
      role: "CUSTOMER_OWNER",
    })),
    permissions: [],
  };
}

function Harness() {
  const {
    activeOrganizationId,
    hasCustomerContext,
    organizations,
    selectOrganization,
  } = useActiveOrganization();
  return (
    <div>
      <p data-testid="active">{activeOrganizationId ?? "none"}</p>
      <p data-testid="hasContext">{String(hasCustomerContext)}</p>
      <button onClick={() => selectOrganization("b")}>select-b</button>
      <button onClick={() => selectOrganization("evil")}>select-evil</button>
      <p data-testid="count">{organizations.length}</p>
    </div>
  );
}

function renderWith(session: SessionSnapshot) {
  return render(
    <SessionProvider initialSession={session}>
      <OrganizationProvider>
        <Harness />
      </OrganizationProvider>
    </SessionProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("active organization context", () => {
  it("auto-selects the single customer organization", () => {
    renderWith(authenticatedWith(["a"]));
    expect(screen.getByTestId("active")).toHaveTextContent("a");
    expect(screen.getByTestId("hasContext")).toHaveTextContent("true");
  });

  it("reports no customer context when there are no customer organizations", () => {
    renderWith(authenticatedWith([]));
    expect(screen.getByTestId("active")).toHaveTextContent("none");
    expect(screen.getByTestId("hasContext")).toHaveTextContent("false");
  });

  it("switches to another authorized organization and persists it", () => {
    renderWith(authenticatedWith(["a", "b"]));
    expect(screen.getByTestId("active")).toHaveTextContent("a");
    fireEvent.click(screen.getByText("select-b"));
    expect(screen.getByTestId("active")).toHaveTextContent("b");
    expect(window.localStorage.getItem("sbj.activeOrganizationId")).toBe("b");
  });

  it("ignores an attempt to select an unauthorized organization", () => {
    renderWith(authenticatedWith(["a", "b"]));
    fireEvent.click(screen.getByText("select-evil"));
    expect(screen.getByTestId("active")).toHaveTextContent("a");
  });

  it("discards a stale stored organization id not in the authorized set", () => {
    window.localStorage.setItem("sbj.activeOrganizationId", "gone");
    renderWith(authenticatedWith(["a", "b"]));
    // Falls back to the first authorized org rather than trusting the stale id.
    expect(screen.getByTestId("active")).toHaveTextContent("a");
  });
});
