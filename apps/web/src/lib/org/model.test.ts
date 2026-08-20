import { describe, expect, it } from "vitest";

import {
  canSelectOrganization,
  resolveActiveOrganization,
} from "@/lib/org/model";
import type { CustomerOrganization } from "@/lib/session/model";

const orgs: CustomerOrganization[] = [
  { organizationId: "a", role: "CUSTOMER_OWNER" },
  { organizationId: "b", role: "CUSTOMER_ASSISTANT" },
];

describe("resolveActiveOrganization", () => {
  it("auto-selects the single organization", () => {
    expect(resolveActiveOrganization([orgs[0]], null)).toEqual({
      activeId: "a",
      discardedStale: false,
    });
  });

  it("keeps a valid stored id", () => {
    expect(resolveActiveOrganization(orgs, "b")).toEqual({
      activeId: "b",
      discardedStale: false,
    });
  });

  it("discards a stale/unauthorized stored id and falls back", () => {
    expect(resolveActiveOrganization(orgs, "zzz")).toEqual({
      activeId: "a",
      discardedStale: true,
    });
    expect(resolveActiveOrganization([], "zzz")).toEqual({
      activeId: null,
      discardedStale: true,
    });
  });

  it("returns no active organization when there are none", () => {
    expect(resolveActiveOrganization([], null)).toEqual({
      activeId: null,
      discardedStale: false,
    });
  });
});

describe("canSelectOrganization", () => {
  it("permits only authorized organization ids", () => {
    expect(canSelectOrganization(orgs, "a")).toBe(true);
    expect(canSelectOrganization(orgs, "zzz")).toBe(false);
  });
});
