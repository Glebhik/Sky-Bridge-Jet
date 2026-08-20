import { afterEach, describe, expect, it } from "vitest";

import { isDemoPortalEnabled } from "@/lib/demo/config";

afterEach(() => {
  delete process.env.DEMO_PORTAL_ENABLED;
  window.history.replaceState(null, "", "/");
});

describe("server-only demo feature flag", () => {
  it.each([undefined, "", "false", "TRUE", "1", "yes"])(
    "fails closed for %s",
    (value) => {
      if (value === undefined) delete process.env.DEMO_PORTAL_ENABLED;
      else process.env.DEMO_PORTAL_ENABLED = value;
      expect(isDemoPortalEnabled()).toBe(false);
    },
  );

  it("enables only for the exact server environment value true", () => {
    process.env.DEMO_PORTAL_ENABLED = "true";
    expect(isDemoPortalEnabled()).toBe(true);
  });

  it("cannot be enabled by URL, header, or cookie-like request input", () => {
    process.env.DEMO_PORTAL_ENABLED = "false";
    window.history.replaceState(null, "", "/demo?DEMO_PORTAL_ENABLED=true");
    document.cookie = "DEMO_PORTAL_ENABLED=true; path=/";
    const attackerControlledHeaders = new Headers({
      "x-demo-portal-enabled": "true",
    });

    expect(attackerControlledHeaders.get("x-demo-portal-enabled")).toBe("true");
    expect(isDemoPortalEnabled()).toBe(false);
  });
});
