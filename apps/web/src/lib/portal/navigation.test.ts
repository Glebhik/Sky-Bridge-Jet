import { describe, expect, it } from "vitest";

import { PORTAL_NAV_ITEMS, isActiveNavItem } from "@/lib/portal/navigation";

describe("portal navigation", () => {
  it("includes the Trip requests destination alongside the existing surfaces", () => {
    const labels = PORTAL_NAV_ITEMS.map((item) => item.label);
    expect(labels).toEqual([
      "Dashboard",
      "Trip requests",
      "Bookings",
      "Offers",
      "Account",
    ]);
    expect(
      PORTAL_NAV_ITEMS.find((item) => item.label === "Trip requests")?.href,
    ).toBe("/portal/trip-requests");
  });

  it("marks Trip requests active on the list and on a nested detail route", () => {
    expect(
      isActiveNavItem("/portal/trip-requests", "/portal/trip-requests"),
    ).toBe(true);
    expect(
      isActiveNavItem("/portal/trip-requests/abc-123", "/portal/trip-requests"),
    ).toBe(true);
  });

  it("does not mark Dashboard active on the trip-requests routes", () => {
    expect(isActiveNavItem("/portal/trip-requests", "/portal")).toBe(false);
    expect(isActiveNavItem("/portal/trip-requests/abc-123", "/portal")).toBe(
      false,
    );
  });
});
