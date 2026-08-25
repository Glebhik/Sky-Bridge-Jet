import { expect, request, test } from "@playwright/test";

/**
 * Phase 9.3.B — LOCAL, OPT-IN responsive + console-hygiene check for the create journey.
 * Runs only when `RUN_TRIP_CREATE_E2E=1`. No email (dev verification token).
 */

const enabled = process.env.RUN_TRIP_CREATE_E2E === "1";
const API = process.env.SBJ_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";
const PW = "PassphraseLong12";

const VIEWPORTS = [
  { w: 320, h: 568 },
  { w: 390, h: 844 },
  { w: 768, h: 1024 },
  { w: 1024, h: 768 },
  { w: 1440, h: 900 },
];

test.describe("create-trip responsive + console hygiene (opt-in, local)", () => {
  test.skip(!enabled, "set RUN_TRIP_CREATE_E2E=1 to run");

  test("no horizontal overflow, CTA visible, no console errors at 5 sizes", async ({
    page,
  }) => {
    const email = `e2e-resp-${Date.now()}@example.test`;
    const api = await request.newContext({ baseURL: API });
    const reg = await api.post("/api/v1/auth/register", {
      data: { email, password: PW },
    });
    const token = (await reg.json()).verification_token as string;
    await api.post("/api/v1/auth/verify-email", { data: { token } });
    await api.dispose();

    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PW);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);

    for (const { w, h } of VIEWPORTS) {
      await page.setViewportSize({ width: w, height: h });

      // List page.
      await page.goto("/portal/trip-requests");
      await page.getByRole("link", { name: "New trip request" }).waitFor();
      let overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `list overflow @${w}`).toBeLessThanOrEqual(1);

      // New form.
      await page.goto("/portal/trip-requests/new");
      await page.getByRole("combobox", { name: "From" }).waitFor();
      overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `new-form overflow @${w}`).toBeLessThanOrEqual(1);

      // Airport suggestions open and stay within the viewport width.
      const from = page.getByRole("combobox", { name: "From" });
      await from.click();
      await from.fill("dub");
      const option = page.getByRole("option", { name: /Dublin/ });
      await expect(option).toBeVisible();
      const optBox = await option.boundingBox();
      expect(optBox, `option box @${w}`).not.toBeNull();
      if (optBox) expect(optBox.x + optBox.width).toBeLessThanOrEqual(w + 1);
      await from.press("Escape");

      // Date/time input is usable, and the primary CTA is within the viewport.
      await page.getByLabel("Departure").fill("2027-03-01T09:30");
      const cta = page.getByRole("button", { name: "Create & submit request" });
      const ctaBox = await cta.boundingBox();
      expect(ctaBox, `cta box @${w}`).not.toBeNull();
      if (ctaBox) expect(ctaBox.x + ctaBox.width).toBeLessThanOrEqual(w + 1);
    }

    // No console errors or hydration warnings across the whole run.
    const hydration = consoleErrors.filter((e) => /hydrat/i.test(e));
    expect(hydration, "no hydration errors").toEqual([]);
    expect(consoleErrors, "no console errors").toEqual([]);
  });
});
