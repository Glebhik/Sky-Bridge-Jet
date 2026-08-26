import { expect, request, test } from "@playwright/test";

const enabled = process.env.RUN_CUSTOMER_BOOKING_E2E === "1";
const API = process.env.SBJ_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";
const CUSTOMER_PASSWORD = "CustomerPassphrase12";
const OWNER_EMAIL = "owner95a@example.test";
const OWNER_PASSWORD = "OwnerPassphrase95A";
const DAY_MS = 24 * 60 * 60 * 1000;

test.describe("Phase 9.5.A real customer Booking journey", () => {
  test.skip(!enabled, "set RUN_CUSTOMER_BOOKING_E2E=1 for the disposable runtime");

  test("selected offer → one pending Booking → customer-safe list", async ({
    page,
  }) => {
    const api = await request.newContext({ baseURL: API });
    const customerEmail = `booking-${Date.now()}@example.test`;
    const departure = new Date(Date.now() + 180 * DAY_MS);
    departure.setUTCHours(9, 30, 0, 0);
    const departureInput = departure.toISOString().slice(0, 16);
    const offerValidUntil = new Date(
      departure.getTime() - 60 * 60 * 1000,
    ).toISOString();
    const evidenceExpiry = new Date(Date.now() + 365 * DAY_MS).toISOString();
    expect(Date.parse(offerValidUntil)).toBeGreaterThan(Date.now());
    const registration = await api.post("/api/v1/auth/register", {
      data: { email: customerEmail, password: CUSTOMER_PASSWORD },
    });
    expect(registration.status()).toBe(201);
    const verificationToken = (await registration.json())
      .verification_token as string;
    expect(verificationToken).toBeTruthy();
    expect(
      (
        await api.post("/api/v1/auth/verify-email", {
          data: { token: verificationToken },
        })
      ).ok(),
    ).toBe(true);

    const bookingPosts: Array<{ url: string; body: Record<string, unknown> }> =
      [];
    const forbiddenMutations: string[] = [];
    const consoleErrors: string[] = [];
    page.on("request", (webRequest) => {
      if (webRequest.method() !== "POST") return;
      const pathname = new URL(webRequest.url()).pathname;
      if (pathname === "/api/proxy/bookings")
        bookingPosts.push({
          url: pathname,
          body: webRequest.postDataJSON() as Record<string, unknown>,
        });
      if (/confirm|reject|cancel|payment|stripe/i.test(pathname))
        forbiddenMutations.push(pathname);
    });
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const location = message.location().url;
      const expectedNoBookingRead =
        message.text().includes("Failed to load resource") &&
        location.includes("/api/proxy/trip-requests/") &&
        location.endsWith("/booking");
      if (!expectedNoBookingRead) consoleErrors.push(message.text());
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(customerEmail);
    await page
      .getByLabel("Password", { exact: true })
      .fill(CUSTOMER_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/portal$/);

    await page.goto("/portal/trip-requests/new");
    const from = page.getByRole("combobox", { name: "From" });
    await from.fill("farn");
    await page.getByRole("option", { name: /Farnborough/ }).click();
    const to = page.getByRole("combobox", { name: "To" });
    await to.fill("dub");
    await page.getByRole("option", { name: /Dublin/ }).click();
    await page.getByLabel("Departure").fill(departureInput);
    await page.getByLabel("First name").fill("Ada");
    await page.getByLabel("Last name").fill("Byron");
    await page
      .getByRole("button", { name: "Create & submit request" })
      .click();
    await expect(page).toHaveURL(/\/portal\/trip-requests\/[0-9a-f-]+$/);
    await expect(page.getByText("SUBMITTED", { exact: true })).toBeVisible();
    const tripId = page.url().split("/").pop()!;

    const owner = await request.newContext({ baseURL: API });
    const ownerLogin = await owner.post("/api/v1/auth/login", {
      data: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    });
    expect(ownerLogin.ok()).toBe(true);
    const csrf = (await owner.storageState()).cookies.find(
      (cookie) => cookie.name === "sbj_csrf",
    )?.value;
    expect(csrf).toBeTruthy();
    const headers = { "x-csrf-token": csrf! };

    const operatorResponse = await owner.post("/api/v1/operators", {
      headers,
      data: {
        legal_name: "Phase 9.5A Aviation Limited",
        country_code: "IE",
        contact_email: "operations95a@example.test",
      },
    });
    expect(operatorResponse.status()).toBe(201);
    const operator = (await operatorResponse.json()) as { id: string };
    const aircraftResponse = await owner.post("/api/v1/aircraft", {
      headers,
      data: {
        operator_id: operator.id,
        manufacturer: "Cessna",
        model: "Citation CJ3+",
        category: "LIGHT_JET",
        registration: "EI-B95A",
        passenger_capacity: 7,
      },
    });
    expect(aircraftResponse.status()).toBe(201);
    const aircraft = (await aircraftResponse.json()) as { id: string };

    expect(
      (
        await owner.post(`/api/v1/operators/${operator.id}/admission`, {
          headers,
        })
      ).status(),
    ).toBe(201);
    expect(
      (
        await owner.post(
          `/api/v1/operators/${operator.id}/admission/submit`,
          { headers },
        )
      ).ok(),
    ).toBe(true);
    expect(
      (
        await owner.post(
          `/api/v1/operators/${operator.id}/admission/review`,
          {
            headers,
            data: { action: "APPROVE", actor_type: "PLATFORM_REVIEWER" },
          },
        )
      ).ok(),
    ).toBe(true);
    for (const evidence of [
      {
        evidence_type: "OPERATING_AUTHORITY",
        reference_number: "AOC-95A",
        issuing_authority: "IAA",
        jurisdiction: "IE",
        expiry_date: evidenceExpiry,
      },
      {
        evidence_type: "INSURANCE",
        insurer_name: "Phase 9.5A Insurer",
        reference_number: "POL-95A",
        expiry_date: evidenceExpiry,
      },
    ]) {
      const created = await owner.post(
        `/api/v1/operators/${operator.id}/evidence`,
        { headers, data: evidence },
      );
      expect(created.status()).toBe(201);
      const item = (await created.json()) as { id: string };
      expect(
        (
          await owner.post(`/api/v1/evidence/${item.id}/review`, {
            headers,
            data: { action: "VERIFY", actor_type: "PLATFORM_REVIEWER" },
          })
        ).ok(),
      ).toBe(true);
    }
    expect(
      (
        await owner.post(
          `/api/v1/operators/${operator.id}/aircraft/${aircraft.id}/authorization`,
          { headers, data: { authority_basis: "OWNED" } },
        )
      ).status(),
    ).toBe(201);
    expect(
      (
        await owner.post(
          `/api/v1/operators/${operator.id}/aircraft/${aircraft.id}/authorization/submit`,
          { headers },
        )
      ).ok(),
    ).toBe(true);
    expect(
      (
        await owner.post(
          `/api/v1/operators/${operator.id}/aircraft/${aircraft.id}/authorization/review`,
          {
            headers,
            data: { action: "APPROVE", actor_type: "PLATFORM_REVIEWER" },
          },
        )
      ).ok(),
    ).toBe(true);

    const offerResponse = await owner.post("/api/v1/offers", {
      headers,
      data: {
        trip_request_id: tripId,
        operator_id: operator.id,
        aircraft_id: aircraft.id,
        currency: "EUR",
        operator_amount_minor: 300000,
        tax_amount_minor: 30000,
        valid_until: offerValidUntil,
        included_services: "Catering",
      },
    });
    expect(offerResponse.status()).toBe(201);
    const offer = (await offerResponse.json()) as { id: string };
    expect(
      (
        await owner.post(`/api/v1/offers/${offer.id}/submit`, { headers })
      ).ok(),
    ).toBe(true);
    await owner.dispose();

    await page.reload();
    await expect(page.getByText("EI-B95A")).toBeVisible();
    await page.getByRole("button", { name: "Select offer" }).click();
    await page.getByRole("button", { name: "Select this offer" }).click();
    await expect(page.getByText("Selected", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create booking request" }),
    ).toBeVisible();

    const viewports = [
      { width: 320, height: 568 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
      { width: 1024, height: 768 },
      { width: 1440, height: 900 },
    ];
    const expectNoOverflow = async () =>
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth >
            document.documentElement.clientWidth,
        ),
      ).toBe(false);

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await expectNoOverflow();
    }

    await page.getByRole("button", { name: "Create booking request" }).click();
    await expect(page.getByText(/Operator confirmation is still required/)).toBeVisible();
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await expectNoOverflow();
      for (const action of ["Keep offer selected", "Create booking request"])
        expect(
          await page
            .getByRole("button", { name: action })
            .evaluate((button) => button.getBoundingClientRect().height),
        ).toBeGreaterThanOrEqual(44);
    }
    const create = page.getByRole("button", {
      name: "Create booking request",
    });
    await create.dblclick();
    await expect(page.getByText("Booking request created")).toBeVisible();
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await expectNoOverflow();
      await expect(page.getByText(/SBJ-.*Awaiting operator confirmation/)).toBeVisible();
      await expect(page.getByRole("link", { name: "View bookings" })).toBeVisible();
    }
    expect(bookingPosts).toHaveLength(1);
    expect(bookingPosts[0].url).toBe("/api/proxy/bookings");
    expect(bookingPosts[0].body).toEqual({
      trip_request_id: tripId,
      operator_offer_id: offer.id,
    });
    expect(Object.keys(bookingPosts[0].body)).toEqual([
      "trip_request_id",
      "operator_offer_id",
    ]);

    await page.getByRole("link", { name: "View bookings" }).click();
    await expect(page).toHaveURL(/\/portal\/bookings$/);
    await expect(page.getByText("Awaiting operator confirmation")).toBeVisible();
    await expect(page.getByText("Phase 9.5A Aviation Limited")).toBeVisible();
    await expect(page.getByText(/Cessna Citation CJ3\+/)).toBeVisible();
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await expectNoOverflow();
      for (const text of [
        "Awaiting operator confirmation",
        "Phase 9.5A Aviation Limited",
        "€3,570.00 EUR",
      ])
        await expect(page.getByText(text, { exact: true })).toBeVisible();
      expect(
        await page
          .getByText("Phase 9.5A Aviation Limited", { exact: true })
          .evaluate((node) => node.scrollWidth <= node.clientWidth),
      ).toBe(true);
      expect(
        await page
          .getByText(/Cessna Citation CJ3\+/)
          .evaluate((node) => node.scrollWidth <= node.clientWidth),
      ).toBe(true);
    }

    const assertions = await page.evaluate(async () => {
      const [trips, bookings, payments] = await Promise.all([
        fetch("/api/proxy/me/trip-requests").then((response) => response.json()),
        fetch("/api/proxy/me/bookings").then((response) => response.json()),
        fetch("/api/proxy/me/payments").then((response) => response.json()),
      ]);
      return { trips, bookings, payments };
    });
    expect(assertions.trips).toHaveLength(1);
    expect(assertions.trips[0].status).toBe("SUBMITTED");
    expect(assertions.bookings).toHaveLength(1);
    expect(assertions.bookings[0].status).toBe(
      "PENDING_OPERATOR_CONFIRMATION",
    );
    expect(assertions.bookings[0].trip_request_id).toBe(tripId);
    expect(assertions.bookings[0].operator_offer_id).toBe(offer.id);
    expect(assertions.payments).toHaveLength(0);
    expect(forbiddenMutations).toEqual([]);
    expect(consoleErrors).toEqual([]);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/portal/bookings");
    await expect(page).toHaveURL(/\/login/);
    await api.dispose();
  });
});
