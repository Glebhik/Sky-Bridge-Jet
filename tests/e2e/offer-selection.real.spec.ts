import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const enabled = process.env.RUN_OFFER_SELECTION_E2E === "1";
const fixture = enabled
  ? (JSON.parse(readFileSync("/tmp/sbj94b-e2e.json", "utf8")) as {
      email: string;
      password: string;
      tripId: string;
      offerId: string;
      otherOfferId: string;
      operatorName: string;
      selectedAircraftRegistration: string;
      otherAircraftRegistration: string;
    })
  : null;

test.describe("Phase 9.4.B real customer offer selection", () => {
  test.skip(
    !enabled,
    "set RUN_OFFER_SELECTION_E2E=1 with the disposable fixture",
  );

  test("confirms and selects exactly once without booking or payment", async ({
    page,
  }) => {
    const selectionRequests: Array<{ url: string; body: string | null }> = [];
    const customerMutations: string[] = [];
    const consoleErrors: string[] = [];
    let customerJourneyStarted = false;
    page.on("request", (request) => {
      if (!customerJourneyStarted || request.method() === "GET") return;
      customerMutations.push(request.url());
      if (
        request.method() === "POST" &&
        request.url().endsWith(`/offers/${fixture!.offerId}/select`)
      )
        selectionRequests.push({
          url: request.url(),
          body: request.postData(),
        });
    });
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(fixture!.email);
    await page.getByLabel("Password", { exact: true }).fill(fixture!.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);
    customerJourneyStarted = true;

    for (const viewport of [
      { width: 320, height: 568 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
      { width: 1024, height: 768 },
      { width: 1440, height: 900 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto(`/portal/trip-requests/${fixture!.tripId}`);
      await expect(page.getByText(fixture!.operatorName).first()).toBeVisible();
      await expect(page.getByRole("article")).toHaveCount(2);
      await expect(
        page.getByText(fixture!.selectedAircraftRegistration),
      ).toBeVisible();
      await expect(
        page.getByText(fixture!.otherAircraftRegistration),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth,
        ),
      ).toBe(false);
    }

    await page.getByRole("button", { name: "Select offer" }).first().click();
    await expect(page.getByText(/does not create a booking/)).toBeVisible();
    const confirm = page.getByRole("button", { name: "Select this offer" });
    await confirm.dblclick();
    await expect(page.getByText("Selected", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /select/i })).toHaveCount(0);
    await expect(page.getByText("SUBMITTED", { exact: true })).toBeVisible();
    await expect(
      page
        .getByRole("article")
        .filter({ hasText: fixture!.selectedAircraftRegistration })
        .getByText("Selected", { exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("article")
        .filter({ hasText: fixture!.otherAircraftRegistration })
        .getByText("Available", { exact: true }),
    ).toBeVisible();
    expect(selectionRequests).toHaveLength(1);
    expect(new URL(selectionRequests[0].url).pathname).toBe(
      `/api/proxy/trip-requests/${fixture!.tripId}/offers/${fixture!.offerId}/select`,
    );
    expect(selectionRequests[0].body).toBeNull();
    expect(customerMutations).toEqual([selectionRequests[0].url]);
    expect(consoleErrors).toEqual([]);
  });
});
