import { writeFileSync } from "node:fs";

import { expect, request, test } from "@playwright/test";

/**
 * Phase 9.3.B — LOCAL, OPT-IN real create-a-trip-request journey.
 *
 * Runs only when `RUN_TRIP_CREATE_E2E=1`. It uses NO email: the account is made ACTIVE via the
 * dev-only `verification_token` that `/auth/register` returns outside production, which also
 * auto-provisions the personal CUSTOMER organization. The browser then drives the real UI:
 * login → trip-requests → New trip request → pick real seeded airports → add a passenger →
 * create DRAFT (never sending customer_id) → submit the SAME DRAFT → SUBMITTED detail → list.
 *
 * It asserts the two mutation payloads carry NO `customer_id`, and writes the created ids to
 * `/tmp/sbj-e2e-out.json` for out-of-band DB assertions.
 */

const enabled = process.env.RUN_TRIP_CREATE_E2E === "1";
const API = process.env.SBJ_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";
const PW = "PassphraseLong12";

test.describe("real create-trip-request journey (opt-in, local only)", () => {
  test.skip(!enabled, "set RUN_TRIP_CREATE_E2E=1 to run the local trip-create E2E");

  test("login → create DRAFT (no customer_id) → submit → SUBMITTED → list", async ({
    page,
  }) => {
    const email = `e2e-trip-${Date.now()}@example.test`;

    // 1. Seed an ACTIVE, auto-provisioned customer WITHOUT email (dev verification token).
    const api = await request.newContext({ baseURL: API });
    const reg = await api.post("/api/v1/auth/register", {
      data: { email, password: PW },
    });
    expect(reg.ok()).toBeTruthy();
    const token = (await reg.json()).verification_token as string;
    expect(token, "dev verification_token required (non-prod)").toBeTruthy();
    const ver = await api.post("/api/v1/auth/verify-email", {
      data: { token },
    });
    expect((await ver.json()).status).toBe("ACTIVE");

    // 2. Capture the mutation payloads the browser sends through the proxy.
    const passengerBodies: string[] = [];
    const tripBodies: string[] = [];
    const submitPaths: string[] = [];
    page.on("request", (req) => {
      const url = req.url();
      if (req.method() !== "POST") return;
      if (url.endsWith("/api/proxy/passengers"))
        passengerBodies.push(req.postData() ?? "");
      else if (url.endsWith("/api/proxy/trip-requests"))
        tripBodies.push(req.postData() ?? "");
      else if (/\/api\/proxy\/trip-requests\/[0-9a-f-]+\/submit$/.test(url))
        submitPaths.push(url);
    });

    // 3. Real browser login.
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PW);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);

    // 4. To the list, then the create page.
    await page.goto("/portal/trip-requests");
    await page.getByRole("link", { name: "New trip request" }).click();
    await expect(page).toHaveURL(/\/portal\/trip-requests\/new$/);

    // 5. Pick two real seeded airports via the combobox.
    const from = page.getByRole("combobox", { name: "From" });
    await from.click();
    await from.fill("farn");
    await page.getByRole("option", { name: /Farnborough/ }).click();
    const to = page.getByRole("combobox", { name: "To" });
    await to.click();
    await to.fill("dub");
    await page.getByRole("option", { name: /Dublin/ }).click();

    await page.getByLabel("Departure").fill("2027-03-01T09:30");
    await page.getByLabel("First name").fill("Ada");
    await page.getByLabel("Last name").fill("Byron");

    // 6. Create + submit.
    await page.getByRole("button", { name: "Create & submit request" }).click();

    // 7. Navigated to the real detail page; SUBMITTED is shown.
    await expect(page).toHaveURL(/\/portal\/trip-requests\/[0-9a-f-]+$/);
    await expect(page.getByText("SUBMITTED")).toBeVisible();
    const tripId = page.url().split("/").pop() ?? "";

    // 8. The mutation payloads never contained customer_id.
    expect(passengerBodies).toHaveLength(1);
    expect(tripBodies).toHaveLength(1);
    expect(submitPaths).toHaveLength(1);
    for (const body of [...passengerBodies, ...tripBodies]) {
      expect(body).not.toContain("customer_id");
    }
    expect(JSON.parse(tripBodies[0]).passenger_ids).toHaveLength(1);

    // 9. Back on the list, the new request appears.
    await page.goto("/portal/trip-requests");
    await expect(
      page.getByRole("link", { name: new RegExp(tripId.slice(0, 8), "i") }),
    ).toBeVisible();

    // 10. Read-model cross-checks via the proxy (org header from the active-org store).
    const summary = await page.evaluate(async () => {
      const org = localStorage.getItem("sbj.activeOrganizationId");
      const headers = org ? { "x-organization-id": org } : undefined;
      const list = await (
        await fetch("/api/proxy/me/trip-requests", { headers })
      ).json();
      const bookings = await (
        await fetch("/api/proxy/me/bookings", { headers })
      ).json();
      const payments = await (
        await fetch("/api/proxy/me/payments", { headers })
      ).json();
      return { org, list, bookings, payments };
    });
    expect(Array.isArray(summary.list)).toBeTruthy();
    expect(summary.list).toHaveLength(1);
    expect(summary.list[0].status).toBe("SUBMITTED");
    expect(summary.list[0].legs).toHaveLength(1);
    expect(summary.list[0].passengers).toHaveLength(1);
    expect(summary.bookings).toHaveLength(0);
    expect(summary.payments).toHaveLength(0);

    writeFileSync(
      "/tmp/sbj-e2e-out.json",
      JSON.stringify({ email, tripId, org: summary.org }),
    );
    await api.dispose();
  });
});
