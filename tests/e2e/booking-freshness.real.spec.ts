import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const enabled = process.env.RUN_BOOKING_FRESHNESS_E2E === "1";
const fixture = enabled
  ? (JSON.parse(readFileSync("/tmp/sbj95c-e2e.json", "utf8")) as {
      customerEmail: string;
      customerPassword: string;
      operatorEmail: string;
      operatorPassword: string;
      confirmReference: string;
      rejectReference: string;
    })
  : null;

test.describe("Phase 9.5.C real two-sided Booking freshness", () => {
  test.describe.configure({ mode: "serial" });
  test.skip(
    !enabled,
    "set RUN_BOOKING_FRESHNESS_E2E=1 with the disposable fixture",
  );

  test("open customer list receives real confirm and reject decisions", async ({
    browser,
  }) => {
    const customerContext = await browser.newContext();
    const operatorContext = await browser.newContext();
    const customer = await customerContext.newPage();
    const operator = await operatorContext.newPage();
    const customerReads: string[] = [];
    const customerPosts: string[] = [];
    const operatorDecisions: string[] = [];
    const consoleErrors: string[] = [];

    customer.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (request.method() === "GET" && path === "/api/proxy/me/bookings")
        customerReads.push(path);
      if (request.method() === "POST") customerPosts.push(path);
    });
    operator.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (
        request.method() === "POST" &&
        /\/api\/proxy\/bookings\/[0-9a-f-]+\/(confirm|reject)$/.test(path)
      )
        operatorDecisions.push(path);
    });
    for (const page of [customer, operator])
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });

    await customer.goto("/login");
    await customer.getByLabel("Email").fill(fixture!.customerEmail);
    await customer
      .getByLabel("Password", { exact: true })
      .fill(fixture!.customerPassword);
    await customer.getByRole("button", { name: "Sign in" }).click();
    await expect(customer).toHaveURL(/\/portal$/);
    await customer.goto("/portal/bookings");
    await expect(
      customer.getByText("Awaiting operator confirmation"),
    ).toHaveCount(2);
    await expect(customer.getByText(fixture!.confirmReference)).toBeVisible();
    await expect(customer.getByText(fixture!.rejectReference)).toBeVisible();
    expect(customerReads.length).toBeGreaterThanOrEqual(1);
    customerPosts.length = 0;

    for (const viewport of [
      { width: 320, height: 568 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
      { width: 1024, height: 768 },
      { width: 1440, height: 900 },
    ]) {
      await customer.setViewportSize(viewport);
      expect(
        await customer.evaluate(
          () =>
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth,
        ),
      ).toBe(false);
      expect(
        await customer
          .getByRole("button", { name: "Refresh status" })
          .evaluate((node) => node.getBoundingClientRect().height),
      ).toBeGreaterThanOrEqual(44);
    }

    await operator.goto("/login");
    await operator.getByLabel("Email").fill(fixture!.operatorEmail);
    await operator
      .getByLabel("Password", { exact: true })
      .fill(fixture!.operatorPassword);
    await operator.getByRole("button", { name: "Sign in" }).click();
    await expect(operator).toHaveURL(/\/portal$/);
    await operator.goto("/operator/bookings");
    await expect(operator).toHaveURL(/\/operator\/bookings$/);

    const confirmCard = operator
      .getByRole("article")
      .filter({ hasText: fixture!.confirmReference });
    await confirmCard.getByRole("button", { name: "Review decision" }).click();
    await confirmCard.getByRole("button", { name: "Confirm booking" }).click();
    await expect(confirmCard).toHaveCount(0);
    expect(
      operatorDecisions.filter((path) => path.endsWith("/confirm")),
    ).toHaveLength(1);

    const readsBeforeConfirmFocus = customerReads.length;
    await customer.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(customer.getByText("Confirmed by the operator")).toBeVisible();
    expect(customerReads).toHaveLength(readsBeforeConfirmFocus + 1);
    await expect(customer.getByText(fixture!.rejectReference)).toBeVisible();

    const rejectCard = operator
      .getByRole("article")
      .filter({ hasText: fixture!.rejectReference });
    await rejectCard.getByRole("button", { name: "Review decision" }).click();
    await rejectCard
      .getByLabel("Rejection reason")
      .selectOption("AIRCRAFT_UNAVAILABLE");
    await rejectCard.getByRole("button", { name: "Reject booking" }).click();
    await expect(rejectCard).toHaveCount(0);
    expect(
      operatorDecisions.filter((path) => path.endsWith("/reject")),
    ).toHaveLength(1);

    const readsBeforeRejectFocus = customerReads.length;
    await customer.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(
      customer.getByText("The operator could not confirm this booking"),
    ).toBeVisible();
    expect(customerReads).toHaveLength(readsBeforeRejectFocus + 1);
    expect(customerPosts).toEqual([]);
    expect(consoleErrors).toEqual([]);

    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1440, height: 900 },
    ]) {
      await operator.setViewportSize(viewport);
      expect(
        await operator.evaluate(
          () =>
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth,
        ),
      ).toBe(false);
    }

    const customerPayload = await customer.evaluate(async () =>
      fetch("/api/proxy/me/bookings").then((response) => response.json()),
    );
    expect(customerPayload).toHaveLength(2);
    expect(
      customerPayload.map((item: { status: string }) => item.status).sort(),
    ).toEqual(["CONFIRMED", "REJECTED"]);
    const serialized = JSON.stringify(customerPayload);
    for (const forbidden of [
      "operator_id",
      "aircraft_id",
      "operator_amount",
      "platform_fee",
      "confirmation_reference",
      "rejection_note",
      "payment_provider",
    ])
      expect(serialized).not.toContain(forbidden);

    await customerContext.close();
    await operatorContext.close();
  });

  test("terminal list retains data and contains a safe transient warning", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(fixture!.customerEmail);
    await page
      .getByLabel("Password", { exact: true })
      .fill(fixture!.customerPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);
    await page.goto("/portal/bookings");
    await expect(page.getByText(fixture!.confirmReference)).toBeVisible();
    await expect(page.getByText(fixture!.rejectReference)).toBeVisible();

    await page.route("**/api/proxy/me/bookings", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "unsafe_internal", message: "raw backend secret" },
        }),
      });
    });
    await page.getByRole("button", { name: "Refresh status" }).click();
    await expect(
      page.getByText("Booking status could not be refreshed."),
    ).toBeVisible();
    await expect(page.getByText(fixture!.confirmReference)).toBeVisible();
    await expect(page.getByText(fixture!.rejectReference)).toBeVisible();
    await expect(page.getByText("raw backend secret")).toHaveCount(0);

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
      await expect(
        page.getByText("Booking status could not be refreshed."),
      ).toBeVisible();
      expect(
        await page
          .getByRole("button", { name: "Refresh status" })
          .evaluate((node) => node.getBoundingClientRect().height),
      ).toBeGreaterThanOrEqual(44);
    }
  });
});
