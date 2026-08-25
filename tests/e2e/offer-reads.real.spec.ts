import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const enabled = process.env.RUN_OFFER_READS_E2E === "1";
const fixture = enabled ? JSON.parse(readFileSync("/tmp/sbj94a-e2e.json", "utf8")) as { email: string; password: string; tripId: string; draftId: string; operatorName: string } : null;

test.describe("Phase 9.4.A real customer offer reads", () => {
  test.skip(!enabled, "set RUN_OFFER_READS_E2E=1 with the disposable fixture");
  test("published offers render factually at every viewport without mutations", async ({ page }) => {
    const mutations: string[] = [];
    const consoleErrors: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET" && request.url().includes("/offers")) mutations.push(request.url());
    });
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    await page.goto("/login");
    await page.getByLabel("Email").fill(fixture!.email);
    await page.getByLabel("Password", { exact: true }).fill(fixture!.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);
    for (const viewport of [{ width: 320, height: 568 }, { width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 1024, height: 768 }, { width: 1440, height: 900 }]) {
      await page.setViewportSize(viewport);
      await page.goto(`/portal/trip-requests/${fixture!.tripId}`);
      await expect(page.getByRole("heading", { name: "Offers" })).toBeVisible();
      await expect(page.getByText(fixture!.operatorName).first()).toBeVisible();
      await expect(page.getByText("Available").first()).toBeVisible();
      await expect(page.getByText("Expired", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /select|book|pay/i })).toHaveCount(0);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow).toBe(false);
    }
    expect(await page.locator("body").textContent()).not.toContain(fixture!.draftId);
    expect(mutations).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
