import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { DEMO_DATA_BANNER, demoFixtures } from "@/lib/demo/fixtures";

const FORBIDDEN_FIELDS = [
  "operator_internal_amount",
  "platform_fee",
  "allocation",
  "settlement_eligibility",
  "provider_reference",
  "provider_references",
  "internal_notes",
  "idempotency_key",
  "payment_data",
  "aircraft_registration",
] as const;

describe("isolated demonstration fixtures", () => {
  it("contains only clearly synthetic identities and identifiers", () => {
    const serialized = JSON.stringify(demoFixtures);
    expect(demoFixtures.customer.name).toBe("Demo Customer");
    expect(demoFixtures.customer.organization).toBe("Demo Travel Office");
    expect(serialized).not.toMatch(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
    expect(serialized).not.toMatch(/\+?\d[\d\s()-]{7,}\d/);
    for (const id of [
      demoFixtures.upcomingTrip.id,
      ...demoFixtures.bookings.map((booking) => booking.id),
      ...demoFixtures.offers.map((offer) => offer.id),
    ]) {
      expect(id).toMatch(/^DEMO-/);
    }
  });

  it("contains no confidential internal financial or operational fields", () => {
    const serialized = JSON.stringify(demoFixtures).toLowerCase();
    for (const field of FORBIDDEN_FIELDS) {
      expect(serialized).not.toContain(field);
    }
    expect(serialized).not.toContain("operator");
    expect(DEMO_DATA_BANNER).toBe(
      "Demonstration Preview — synthetic data only. No booking or transaction is created.",
    );
  });

  it("is never imported by production portal, API, proxy, auth, or session modules", () => {
    const productionFiles = [
      "../../app/portal/layout.tsx",
      "../api/client.ts",
      "../../proxy.ts",
      "../auth/redirect.ts",
      "../session/server.ts",
    ];
    for (const relativePath of productionFiles) {
      const source = readFileSync(
        fileURLToPath(new URL(relativePath, import.meta.url)),
        "utf8",
      );
      expect(source).not.toContain("@/lib/demo/");
    }
  });
});
