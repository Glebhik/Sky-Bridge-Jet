import { readFileSync } from "node:fs";

import { expect, request, test } from "@playwright/test";

const enabled = process.env.RUN_OFFERS_FRESHNESS_E2E === "1";
const fixture = enabled
  ? (JSON.parse(readFileSync("/tmp/sbj94c-e2e.json", "utf8")) as {
      customerEmail: string;
      customerPassword: string;
      operatorEmail: string;
      operatorPassword: string;
      operatorOrganizationId: string;
      operatorId: string;
      aircraftId: string;
      tripId: string;
      offerAId: string;
      offerARegistration: string;
      offerBRegistration: string;
      draftRegistration: string;
      operatorName: string;
    })
  : null;

test.describe("Phase 9.4.C real offers lifecycle and freshness", () => {
  test.skip(
    !enabled,
    "set RUN_OFFERS_FRESHNESS_E2E=1 with the disposable fixture",
  );

  test("lands, discovers a newly published offer on focus, and selects once", async ({
    page,
  }) => {
    const offerListReads: string[] = [];
    const landingOfferReads: string[] = [];
    const selectionRequests: Array<{ url: string; body: string | null }> = [];
    const forbiddenMutations: string[] = [];
    const consoleErrors: string[] = [];
    let onLanding = false;
    page.on("request", (webRequest) => {
      const url = webRequest.url();
      const pathname = new URL(url).pathname;
      if (
        webRequest.method() === "GET" &&
        pathname.startsWith("/api/proxy/trip-requests/") &&
        pathname.endsWith("/offers")
      ) {
        offerListReads.push(url);
        if (onLanding) landingOfferReads.push(url);
      }
      if (
        webRequest.method() === "POST" &&
        url.endsWith(`/offers/${fixture!.offerAId}/select`)
      )
        selectionRequests.push({ url, body: webRequest.postData() });
      if (webRequest.method() === "POST" && /booking|payment|stripe/i.test(url))
        forbiddenMutations.push(url);
    });
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(fixture!.customerEmail);
    await page
      .getByLabel("Password", { exact: true })
      .fill(fixture!.customerPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);

    onLanding = true;
    await page.goto("/portal/offers");
    await expect(page.getByRole("heading", { name: "Offers" })).toBeVisible();
    await expect(
      page.getByRole("link", {
        name: new RegExp(fixture!.tripId.slice(0, 8), "i"),
      }),
    ).toBeVisible();
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1440, height: 900 },
    ]) {
      await page.setViewportSize(viewport);
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth,
        ),
      ).toBe(false);
    }
    expect(landingOfferReads).toEqual([]);
    onLanding = false;
    await page
      .getByRole("link", { name: new RegExp(fixture!.tripId.slice(0, 8), "i") })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/portal/trip-requests/${fixture!.tripId}$`),
    );
    await expect(page.getByText(fixture!.offerARegistration)).toBeVisible();
    await expect(page.getByText(fixture!.draftRegistration)).toHaveCount(0);
    const readsBeforePublish = offerListReads.length;

    const apiOrigin =
      process.env.SBJ_E2E_API_ORIGIN ?? "http://127.0.0.1:8000/api/v1";
    const api = await request.newContext({
      baseURL: `${apiOrigin.replace(/\/$/, "")}/`,
    });
    const login = await api.post("auth/login", {
      data: {
        email: fixture!.operatorEmail,
        password: fixture!.operatorPassword,
      },
    });
    expect(login.ok()).toBe(true);
    const csrf = (await api.storageState()).cookies.find(
      (cookie) => cookie.name === "sbj_csrf",
    )?.value;
    expect(csrf).toBeTruthy();
    const created = await api.post("offers", {
      headers: {
        "x-csrf-token": csrf!,
        "x-organization-id": fixture!.operatorOrganizationId,
      },
      data: {
        trip_request_id: fixture!.tripId,
        operator_id: fixture!.operatorId,
        aircraft_id: fixture!.aircraftId,
        currency: "EUR",
        operator_amount_minor: 275000,
        tax_amount_minor: 25000,
        valid_until: "2099-12-31T23:59:59Z",
        included_services: "Freshness E2E catering",
      },
    });
    expect(created.status()).toBe(201);
    const offerB = (await created.json()) as { id: string };
    const submitted = await api.post(`offers/${offerB.id}/submit`, {
      headers: {
        "x-csrf-token": csrf!,
        "x-organization-id": fixture!.operatorOrganizationId,
      },
    });
    expect(submitted.ok()).toBe(true);
    await api.dispose();

    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(page.getByText(fixture!.offerBRegistration)).toBeVisible();
    expect(offerListReads.length).toBe(readsBeforePublish + 1);

    for (const viewport of [
      { width: 320, height: 568 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
      { width: 1024, height: 768 },
      { width: 1440, height: 900 },
    ]) {
      await page.setViewportSize(viewport);
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth,
        ),
      ).toBe(false);
    }

    await page
      .getByRole("article")
      .filter({ hasText: fixture!.offerARegistration })
      .getByRole("button", { name: "Select offer" })
      .click();
    await page.getByRole("button", { name: "Select this offer" }).dblclick();
    await expect(
      page
        .getByRole("article")
        .filter({ hasText: fixture!.offerARegistration })
        .getByText("Selected", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("SUBMITTED", { exact: true })).toBeVisible();
    expect(selectionRequests).toHaveLength(1);
    expect(selectionRequests[0].body).toBeNull();
    expect(forbiddenMutations).toEqual([]);
    expect(consoleErrors).toEqual([]);

    await page.reload();
    await expect(
      page
        .getByRole("article")
        .filter({ hasText: fixture!.offerARegistration })
        .getByText("Selected", { exact: true }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    const denied = await page.request.get("/api/proxy/me");
    expect(denied.status()).toBe(401);
    await page.goto("/portal/offers");
    await expect(page).toHaveURL(/\/login$/);
  });
});
