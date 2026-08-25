import { expect, request, test } from "@playwright/test";

/**
 * Phase 9.3.C — LOCAL, OPT-IN responsive + console-hygiene check for the dashboard summary
 * and the cancel confirmation UX. Runs only when `RUN_TRIP_CREATE_E2E=1`. No email.
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

test.describe("dashboard + cancel responsive (opt-in, local)", () => {
  test.skip(!enabled, "set RUN_TRIP_CREATE_E2E=1 to run");

  test("no overflow, cancel confirmation reachable, no console errors at 5 sizes", async ({
    page,
  }) => {
    const email = `e2e-c-resp-${Date.now()}@example.test`;
    const api = await request.newContext({ baseURL: API });
    const reg = await api.post("/api/v1/auth/register", {
      data: { email, password: PW },
    });
    const token = (await reg.json()).verification_token as string;
    await api.post("/api/v1/auth/verify-email", { data: { token } });
    await api.dispose();

    const consoleErrors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push(m.text());
    });
    page.on("pageerror", (e) => consoleErrors.push(String(e)));

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PW);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);

    // Create + submit one request so the dashboard has real data and a cancellable detail.
    await page.goto("/portal/trip-requests/new");
    const from = page.getByRole("combobox", { name: "From" });
    await from.click();
    await from.fill("farn");
    await page.getByRole("option", { name: /Farnborough/ }).click();
    const to = page.getByRole("combobox", { name: "To" });
    await to.click();
    await to.fill("dub");
    await page.getByRole("option", { name: /Dublin/ }).click();
    await page.getByLabel("Departure").fill("2027-06-01T09:30");
    await page.getByLabel("First name").fill("Ada");
    await page.getByLabel("Last name").fill("Byron");
    await page.getByRole("button", { name: "Create & submit request" }).click();
    await expect(page).toHaveURL(/\/portal\/trip-requests\/[0-9a-f-]+$/);
    const tripId = page.url().split("/").pop() ?? "";

    for (const { w, h } of VIEWPORTS) {
      await page.setViewportSize({ width: w, height: h });

      // Dashboard: real stats, no horizontal overflow.
      await page.goto("/portal");
      await page.locator(".stat", { hasText: "Total" }).first().waitFor();
      await expect(page.getByRole("link", { name: "New trip request" })).toBeVisible();
      let overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `dashboard overflow @${w}`).toBeLessThanOrEqual(1);

      if (w <= 390) {
        const menuToggle = page.getByRole("button", {
          name: "Open navigation menu",
        });
        await expect(menuToggle).toHaveAttribute("aria-expanded", "false");
        await menuToggle.click();
        await expect(
          page.getByRole("button", { name: "Close navigation menu" }),
        ).toHaveAttribute("aria-expanded", "true");
        await expect(
          page.getByRole("navigation", { name: "Portal" }).getByRole("link", {
            name: "Bookings",
          }),
        ).toBeVisible();
        await page
          .getByRole("button", { name: "Close navigation menu" })
          .click();
        await expect(menuToggle).toHaveAttribute("aria-expanded", "false");
        overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow, `mobile navigation overflow @${w}`).toBeLessThanOrEqual(
          1,
        );
      }

      // List + create route remain readable and keyboard reachable.
      await page.goto("/portal/trip-requests");
      await expect(page.getByRole("link", { name: "New trip request" })).toBeVisible();
      overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `list overflow @${w}`).toBeLessThanOrEqual(1);
      await page.goto("/portal/trip-requests/new");
      await expect(page.getByRole("combobox", { name: "From" })).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Create & submit request" }),
      ).toBeVisible();
      overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `create overflow @${w}`).toBeLessThanOrEqual(1);

      // Detail cancel confirmation: reachable and within the viewport.
      await page.goto(`/portal/trip-requests/${tripId}`);
      const cancel = page.getByRole("button", { name: "Cancel request" });
      await cancel.waitFor();
      await cancel.press("Tab");
      const focusVisible = await page.evaluate(
        () => document.activeElement?.matches(":focus-visible") ?? false,
      );
      expect(focusVisible, `focus-visible @${w}`).toBe(true);
      await cancel.click();
      await expect(page.getByText("Cancel this trip request?")).toBeVisible();
      const confirm = page
        .getByRole("group", { name: "Cancel request" })
        .getByRole("button", { name: "Cancel request" });
      const box = await confirm.boundingBox();
      expect(box, `confirm box @${w}`).not.toBeNull();
      if (box) expect(box.x + box.width).toBeLessThanOrEqual(w + 1);
      overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `detail overflow @${w}`).toBeLessThanOrEqual(1);
      // Keep the request (don't cancel it — reused across viewports).
      await page.getByRole("button", { name: "Keep request" }).click();
    }

    // Exercise the real CANCELLED response after confirming the panel at every viewport.
    await page.goto(`/portal/trip-requests/${tripId}`);
    await page.getByRole("button", { name: "Cancel request" }).click();
    const confirm = page
      .getByRole("group", { name: "Cancel request" })
      .getByRole("button", { name: "Cancel request" });
    await confirm.click();
    await expect(page.getByText("Request cancelled")).toBeVisible();
    await expect(page.getByText("CANCELLED", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel request" })).toHaveCount(0);

    const hydration = consoleErrors.filter((e) => /hydrat/i.test(e));
    expect(hydration, "no hydration errors").toEqual([]);
    expect(consoleErrors, "no console errors").toEqual([]);
  });
});
