import { describe, expect, it } from "vitest";

import type { MeResponse } from "@/lib/api/types";
import {
  deriveCustomerOrganizations,
  hasCustomerContext,
  snapshotFromMe,
} from "@/lib/session/model";

const me: MeResponse = {
  user: {
    id: "u1",
    email: "a@b.co",
    display_name: null,
    status: "ACTIVE",
    email_verified_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
  },
  memberships: [
    {
      organization_id: "c1",
      organization_type: "CUSTOMER",
      role: "CUSTOMER_OWNER",
    },
    {
      organization_id: "o1",
      organization_type: "OPERATOR",
      role: "OPERATOR_ADMIN",
    },
    {
      organization_id: "p1",
      organization_type: "PLATFORM",
      role: "PRODUCT_OWNER",
    },
  ],
  permissions: ["trip.write"],
};

describe("session model", () => {
  it("derives only CUSTOMER organizations (never OPERATOR/PLATFORM)", () => {
    const orgs = deriveCustomerOrganizations(me.memberships);
    expect(orgs).toEqual([{ organizationId: "c1", role: "CUSTOMER_OWNER" }]);
  });

  it("builds an authenticated snapshot with the customer organizations", () => {
    const snapshot = snapshotFromMe(me);
    expect(snapshot.status).toBe("authenticated");
    expect(hasCustomerContext(snapshot)).toBe(true);
  });

  it("flags an authenticated user with no CUSTOMER membership as lacking customer context", () => {
    const operatorOnly = snapshotFromMe({
      ...me,
      memberships: [
        {
          organization_id: "o1",
          organization_type: "OPERATOR",
          role: "OPERATOR_ADMIN",
        },
      ],
    });
    expect(operatorOnly.status).toBe("authenticated");
    expect(hasCustomerContext(operatorOnly)).toBe(false);
  });

  it("reports no customer context for unauthenticated/error snapshots", () => {
    expect(hasCustomerContext({ status: "unauthenticated" })).toBe(false);
    expect(hasCustomerContext({ status: "error", transient: true })).toBe(
      false,
    );
  });
});
