import { writeFileSync } from "node:fs";

import { expect, request, test } from "@playwright/test";

/**
 * Phase 9.3.C — LOCAL, OPT-IN full customer journey: dashboard → create → submit → cancel.
 * Runs only when `RUN_TRIP_CREATE_E2E=1`. No email/Resend/external providers; the account is
 * made ACTIVE via the dev-only registration verification token. It asserts the browser
 * mutation payloads (no customer_id; submit/cancel target the same trip; cancel carries the
 * current expected_version), the real SUBMITTED→CANCELLED transition, dashboard count updates,
 * and that no offers/booking/payment request is ever made. Ids are written for DB assertions.
 */

const enabled = process.env.RUN_TRIP_CREATE_E2E === "1";
const API = process.env.SBJ_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";
const PW = "PassphraseLong12";

function statValue(page: import("@playwright/test").Page, label: string) {
  return page.locator(".stat", { hasText: label }).locator(".stat__value");
}

test.describe("real trip-management journey (opt-in, local only)", () => {
  test.skip(!enabled, "set RUN_TRIP_CREATE_E2E=1 to run the local journey");

  test("dashboard → create → submit → cancel → CANCELLED, counts update", async ({
    page,
  }) => {
    const email = `e2e-mgmt-${Date.now()}@example.test`;

    // 1. Seed an ACTIVE, auto-provisioned customer WITHOUT email.
    const api = await request.newContext({ baseURL: API });
    const reg = await api.post("/api/v1/auth/register", {
      data: { email, password: PW },
    });
    const token = (await reg.json()).verification_token as string;
    expect(token).toBeTruthy();
    const ver = await api.post("/api/v1/auth/verify-email", {
      data: { token },
    });
    expect((await ver.json()).status).toBe("ACTIVE");

    // 2. Capture every browser mutation request.
    const passengerBodies: string[] = [];
    const tripBodies: string[] = [];
    const submitUrls: string[] = [];
    const cancelReqs: { url: string; body: string }[] = [];
    const forbiddenMutations: string[] = [];
    page.on("request", (req) => {
      if (req.method() !== "POST") return;
      const url = req.url();
      if (url.endsWith("/api/proxy/passengers"))
        passengerBodies.push(req.postData() ?? "");
      else if (url.endsWith("/api/proxy/trip-requests"))
        tripBodies.push(req.postData() ?? "");
      else if (/\/trip-requests\/[0-9a-f-]+\/submit$/.test(url))
        submitUrls.push(url);
      else if (/\/trip-requests\/[0-9a-f-]+\/cancel$/.test(url))
        cancelReqs.push({ url, body: req.postData() ?? "" });
      else if (/\/(offers|booking|bookings|payments?)(\/|$)/.test(url))
        forbiddenMutations.push(url);
    });

    // 3. Login.
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PW);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);

    // 4. Dashboard initially reflects an empty real DB state for this new customer.
    await expect(page.getByText("No trip requests yet")).toBeVisible();

    // 5. Create + submit a real trip request (Farnborough → Dublin).
    await page.goto("/portal/trip-requests");
    await page.getByRole("link", { name: "New trip request" }).click();
    const from = page.getByRole("combobox", { name: "From" });
    await from.click();
    await from.fill("farn");
    await page.getByRole("option", { name: /Farnborough/ }).click();
    const to = page.getByRole("combobox", { name: "To" });
    await to.click();
    await to.fill("dub");
    await page.getByRole("option", { name: /Dublin/ }).click();
    await page.getByLabel("Departure").fill("2027-05-01T09:30");
    await page.getByLabel("First name").fill("Ada");
    await page.getByLabel("Last name").fill("Byron");
    await page.getByRole("button", { name: "Create & submit request" }).click();

    await expect(page).toHaveURL(/\/portal\/trip-requests\/[0-9a-f-]+$/);
    await expect(page.getByText("SUBMITTED")).toBeVisible();
    const tripId = page.url().split("/").pop() ?? "";

    // 6. Dashboard reflects the real request.
    await page.goto("/portal");
    await expect(statValue(page, "Total")).toHaveText("1");
    await expect(statValue(page, "Active")).toHaveText("1");
    await expect(statValue(page, "Submitted")).toHaveText("1");
    await expect(statValue(page, "Cancelled")).toHaveText("0");

    // 7. Open the same request and cancel it (explicit confirmation).
    await page.goto(`/portal/trip-requests/${tripId}`);
    await page.getByRole("button", { name: "Cancel request" }).click();
    await expect(page.getByText("Cancel this trip request?")).toBeVisible();
    // The confirm button is the destructive one inside the panel.
    await page
      .getByRole("group", { name: "Cancel request" })
      .getByRole("button", { name: "Cancel request" })
      .click();

    // 8. Same request becomes CANCELLED; the Cancel action disappears.
    await expect(page.getByText("Request cancelled")).toBeVisible();
    await expect(page.getByText("CANCELLED", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Cancel request" }),
    ).toHaveCount(0);

    // 9. List shows CANCELLED.
    await page.goto("/portal/trip-requests");
    await expect(
      page.locator(".resource-list__row", {
        hasText: tripId.slice(0, 8).toUpperCase(),
      }),
    ).toContainText("CANCELLED");

    // 10. Dashboard counts update.
    await page.goto("/portal");
    await expect(statValue(page, "Total")).toHaveText("1");
    await expect(statValue(page, "Active")).toHaveText("0");
    await expect(statValue(page, "Cancelled")).toHaveText("1");

    // 11. /auth/me remains customer-only.
    const me = await page.evaluate(async () => {
      const r = await fetch("/api/proxy/auth/me", { credentials: "include" });
      return r.json();
    });
    expect(me.memberships).toHaveLength(1);
    expect(me.memberships[0].organization_type).toBe("CUSTOMER");

    // 12. Logout → /portal is denied.
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/portal");
    await expect(page).toHaveURL(/\/login\?next=%2Fportal/);

    // ── Network assertions ──────────────────────────────────────────────────────────────────
    expect(passengerBodies).toHaveLength(1);
    expect(tripBodies).toHaveLength(1); // exactly one TripRequest create
    expect(submitUrls).toHaveLength(1);
    expect(cancelReqs).toHaveLength(1); // exactly one cancel
    for (const body of [...passengerBodies, ...tripBodies]) {
      expect(body).not.toContain("customer_id");
    }
    expect(submitUrls[0]).toContain(`/trip-requests/${tripId}/submit`);
    expect(cancelReqs[0].url).toContain(`/trip-requests/${tripId}/cancel`);
    const cancelBody = JSON.parse(cancelReqs[0].body) as {
      expected_version: number;
    };
    expect(cancelBody.expected_version).toBe(2);
    expect("customer_id" in cancelBody).toBe(false);
    expect(forbiddenMutations).toEqual([]);

    writeFileSync(
      "/tmp/sbj-9-3c-e2e-out.json",
      JSON.stringify({ email, tripId, cancelVersion: cancelBody.expected_version }),
    );
    await api.dispose();
  });
});
