import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  document.cookie = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiRequest — success and typed errors", () => {
  it("returns a typed success body and calls the same-origin proxy with credentials", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ user: { id: "1" } }));
    const result = await portalApi.getMe();
    expect(result).toEqual({ user: { id: "1" } });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe("/api/proxy/auth/me");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.cache).toBe("no-store");
  });

  it("maps status codes to distinct ApiError kinds (401 vs 403 vs 409 vs 429 vs 5xx)", async () => {
    const cases: Array<[number, string]> = [
      [401, "auth"],
      [403, "forbidden"],
      [409, "conflict"],
      [429, "rate_limited"],
      [500, "server"],
    ];
    for (const [status, kind] of cases) {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({ error: { code: "c", message: "m" } }, status),
      );
      await expect(apiRequest("auth/me")).rejects.toMatchObject({
        status,
        kind,
      });
    }
  });

  it("classifies a network failure as a transient ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );
    const error = await apiRequest("auth/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("network");
    expect((error as ApiError).isTransient).toBe(true);
  });

  it("treats an empty body as no value and a non-JSON 2xx as malformed", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 204 }),
    );
    await expect(
      apiRequest("auth/logout", { method: "POST" }),
    ).resolves.toBeUndefined();

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("<html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      }),
    );
    await expect(apiRequest("auth/me")).rejects.toMatchObject({
      kind: "malformed",
    });
  });

  it("attaches the CSRF header from the cookie on mutations only", async () => {
    document.cookie = "sbj_csrf=csrf-value";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ message: "ok" })),
      );

    await apiRequest("auth/logout", { method: "POST" });
    const postHeaders = fetchSpy.mock.calls[0][1]?.headers as Headers;
    expect(postHeaders.get("x-csrf-token")).toBe("csrf-value");

    await apiRequest("auth/me");
    const getHeaders = fetchSpy.mock.calls[1][1]?.headers as Headers;
    expect(getHeaders.get("x-csrf-token")).toBeNull();
  });

  it("sends the active organization id as X-Organization-Id when provided", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([]));
    await portalApi.listBookings("org-42");
    const headers = fetchSpy.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("x-organization-id")).toBe("org-42");
  });
});

describe("portalApi — Phase 9.7.C compliance reads", () => {
  it("uses two exact same-origin GETs with org header, no-store, and AbortSignal", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          admission_status: null,
          marketplace_eligible: false,
          blockers: ["OPERATOR_NOT_ADMITTED"],
          created_at: null,
          updated_at: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    const controller = new AbortController();
    await portalApi.getOperatorComplianceReadiness("org-42", controller.signal);
    await portalApi.listOperatorAircraft("org-42", controller.signal);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls.map(([url]) => String(url))).toEqual([
      "/api/proxy/me/operator-compliance-readiness",
      "/api/proxy/me/operator-aircraft?limit=100&offset=0",
    ]);
    for (const [, init] of fetchSpy.mock.calls) {
      expect(init?.method).toBe("GET");
      expect(init?.credentials).toBe("same-origin");
      expect(init?.cache).toBe("no-store");
      expect(init?.signal).toBe(controller.signal);
      const headers = init?.headers as Headers;
      expect(headers.get("x-organization-id")).toBe("org-42");
      expect(headers.get("authorization")).toBeNull();
    }
  });
});

describe("portalApi — Phase 9.7.D aircraft management", () => {
  const id = "11111111-2222-4333-8444-555555555555";
  it("uses exact detail GET and collection POST with org, CSRF and safe body", async () => {
    document.cookie = "sbj_csrf=csrf-97d";
    const item = {
      id,
      registration: "EI-SBJ",
      manufacturer: "Cessna",
      model: "Citation",
      category: "LIGHT_JET",
      passenger_capacity: 7,
      status: "ACTIVE",
      eligible: true,
    };
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([item]))
      .mockResolvedValueOnce(jsonResponse(item))
      .mockResolvedValueOnce(jsonResponse(item));
    const controller = new AbortController();
    await portalApi.listOperatorAircraftPage(
      "org-97d",
      { limit: 20, offset: 40 },
      controller.signal,
    );
    await portalApi.getOperatorAircraft(id, "org-97d", controller.signal);
    await portalApi.createOperatorAircraft(
      {
        registration: "EI-SBJ",
        manufacturer: "Cessna",
        model: "Citation",
        category: "LIGHT_JET",
        passenger_capacity: 7,
      },
      "org-97d",
    );
    expect(fetchSpy.mock.calls.map(([url]) => String(url))).toEqual([
      "/api/proxy/me/operator-aircraft?limit=20&offset=40",
      `/api/proxy/me/operator-aircraft/${id}`,
      "/api/proxy/me/operator-aircraft",
    ]);
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    const post = fetchSpy.mock.calls[2][1];
    expect(post?.method).toBe("POST");
    expect((post?.headers as Headers).get("x-organization-id")).toBe("org-97d");
    expect((post?.headers as Headers).get("x-csrf-token")).toBe("csrf-97d");
    expect(JSON.parse(String(post?.body))).toEqual({
      registration: "EI-SBJ",
      manufacturer: "Cessna",
      model: "Citation",
      category: "LIGHT_JET",
      passenger_capacity: 7,
    });
    expect(String(post?.body)).not.toMatch(/operator_id|status|eligible/);
  });
});

describe("portalApi — Phase 9.2.A account-entry methods", () => {
  it("POSTs each account-entry contract to its exact same-origin proxy path", async () => {
    const cases: Array<[string, () => Promise<unknown>, unknown]> = [
      [
        "/api/proxy/auth/register",
        () => portalApi.register("a@b.co", "PasswordLong12"),
        {
          email: "a@b.co",
          password: "PasswordLong12",
        },
      ],
      [
        "/api/proxy/auth/verify-email",
        () => portalApi.verifyEmail("tok"),
        {
          token: "tok",
        },
      ],
      [
        "/api/proxy/auth/verification/resend",
        () => portalApi.resendVerification("a@b.co"),
        { email: "a@b.co" },
      ],
      [
        "/api/proxy/auth/password-reset",
        () => portalApi.requestPasswordReset("a@b.co"),
        { email: "a@b.co" },
      ],
      [
        "/api/proxy/auth/password-reset/confirm",
        () => portalApi.confirmPasswordReset("tok", "PasswordLong12"),
        { token: "tok", password: "PasswordLong12" },
      ],
    ];
    for (const [expectedUrl, call, expectedBody] of cases) {
      const fetchSpy = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(jsonResponse({ message: "ok" }));
      await call();
      const [url, init] = fetchSpy.mock.calls[0];
      expect(String(url)).toBe(expectedUrl);
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("same-origin");
      expect(JSON.parse(String(init?.body))).toEqual(expectedBody);
      vi.restoreAllMocks();
    }
  });

  it("never stores credentials or tokens in browser storage", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ user: { id: "1" }, verification_token: null }),
      ),
    );
    await portalApi.register("a@b.co", "PasswordLong12");
    await portalApi.confirmPasswordReset("tok", "PasswordLong12");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe("portalApi — Phase 9.3.A trip-request reads", () => {
  const TRIP_ID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";
  const AIRPORT_ID = "11111111-2222-3333-4444-555555555555";

  it("getTripRequest GETs the exact same-origin proxy path with the org header", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ id: TRIP_ID }));
    await portalApi.getTripRequest(TRIP_ID, "org-42");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/trip-requests/${TRIP_ID}`);
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.cache).toBe("no-store");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
    // A read carries no CSRF token (safe method).
    expect((init?.headers as Headers).get("x-csrf-token")).toBeNull();
  });

  it("getAirport GETs the exact same-origin proxy path (public, no org header)", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ id: AIRPORT_ID }));
    await portalApi.getAirport(AIRPORT_ID);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/airports/${AIRPORT_ID}`);
    expect(init?.method ?? "GET").toBe("GET");
    expect((init?.headers as Headers).get("x-organization-id")).toBeNull();
  });

  it("does not write to browser storage on reads", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(jsonResponse({ id: TRIP_ID })),
    );
    await portalApi.getTripRequest(TRIP_ID, "org-42");
    await portalApi.getAirport(AIRPORT_ID);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe("portalApi — Phase 9.5.B operator decisions", () => {
  const BOOKING = "11111111-2222-4333-8444-555555555555";
  it("uses exact queue and decision contracts without operator_id", async () => {
    document.cookie = "sbj_csrf=csrf-95b";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(jsonResponse([])));
    await portalApi.listOperatorBookings("org-95b");
    await portalApi.confirmOperatorBooking(
      BOOKING,
      { confirmation_reference: "REF" },
      "org-95b",
    );
    await portalApi.rejectOperatorBooking(
      BOOKING,
      { reason: "OTHER" },
      "org-95b",
    );
    expect(fetchSpy.mock.calls.map(([url]) => String(url))).toEqual([
      "/api/proxy/me/operator-bookings",
      `/api/proxy/bookings/${BOOKING}/confirm`,
      `/api/proxy/bookings/${BOOKING}/reject`,
    ]);
    for (const [, init] of fetchSpy.mock.calls) {
      expect((init?.headers as Headers).get("x-organization-id")).toBe(
        "org-95b",
      );
    }
    for (const [, init] of fetchSpy.mock.calls.slice(1)) {
      expect((init?.headers as Headers).get("x-csrf-token")).toBe("csrf-95b");
      expect(String(init?.body)).not.toContain("operator_id");
    }
  });
});

describe("portalApi — Phase 9.7.B operator Booking reads", () => {
  const BOOKING = "11111111-2222-4333-8444-555555555555";

  it("uses exact same-origin no-store abortable history/detail contracts", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(jsonResponse([])));
    const controller = new AbortController();
    await portalApi.listOperatorBookingHistory(
      "org-97b",
      { limit: 10, offset: 20, status: "CONFIRMED" },
      controller.signal,
    );
    await portalApi.getOperatorBooking(BOOKING, "org-97b", controller.signal);
    expect(fetchSpy.mock.calls.map(([url]) => String(url))).toEqual([
      "/api/proxy/me/operator-bookings/history?limit=10&offset=20&status=CONFIRMED",
      `/api/proxy/me/operator-bookings/${BOOKING}`,
    ]);
    for (const [, init] of fetchSpy.mock.calls) {
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.credentials).toBe("same-origin");
      expect(init?.cache).toBe("no-store");
      expect(init?.signal).toBe(controller.signal);
      expect((init?.headers as Headers).get("x-organization-id")).toBe(
        "org-97b",
      );
      expect((init?.headers as Headers).get("authorization")).toBeNull();
      expect(String(init?.body ?? "")).not.toContain("operator_id");
    }
  });
});

describe("portalApi — Phase 9.7.A operator Offer contracts", () => {
  const OFFER = "11111111-2222-4333-8444-555555555555";
  it("uses exact paths, active org, CSRF writes and no operator_id", async () => {
    document.cookie = "sbj_csrf=csrf-97a";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(jsonResponse([])));
    await portalApi.listOperatorOpportunities("org-97a");
    await portalApi.listOperatorAircraft("org-97a");
    await portalApi.createOperatorOffer(
      {
        trip_request_id: "trip",
        aircraft_id: "aircraft",
        currency: "EUR",
        operator_amount_minor: 12300,
      },
      "org-97a",
    );
    await portalApi.getOperatorOffer(OFFER, "org-97a");
    await portalApi.updateOperatorOffer(
      OFFER,
      { operator_amount_minor: 12400 },
      "org-97a",
    );
    await portalApi.submitOperatorOffer(OFFER, "org-97a");
    await portalApi.withdrawOperatorOffer(OFFER, "org-97a");
    expect(fetchSpy.mock.calls.map(([url]) => String(url))).toEqual([
      "/api/proxy/me/operator-opportunities?limit=100&offset=0",
      "/api/proxy/me/operator-aircraft?limit=100&offset=0",
      "/api/proxy/me/operator-offers",
      `/api/proxy/offers/${OFFER}`,
      `/api/proxy/offers/${OFFER}`,
      `/api/proxy/offers/${OFFER}/submit`,
      `/api/proxy/offers/${OFFER}/withdraw`,
    ]);
    for (const [, init] of fetchSpy.mock.calls)
      expect((init?.headers as Headers).get("x-organization-id")).toBe(
        "org-97a",
      );
    for (const [, init] of fetchSpy.mock.calls.filter(
      ([, init]) => (init?.method ?? "GET") !== "GET",
    )) {
      expect((init?.headers as Headers).get("x-csrf-token")).toBe("csrf-97a");
      expect(String(init?.body ?? "")).not.toContain("operator_id");
    }
  });
});

describe("portalApi — Phase 9.6.A customer Payment contracts", () => {
  const A = "11111111-2222-4333-8444-555555555555";
  const B = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

  it("sends one authoritative GET with repeated booking_id values", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([]));
    await portalApi.listPayments([A, B], "org-payments");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(
      `/api/proxy/me/payments?booking_id=${A}&booking_id=${B}`,
    );
    expect(init?.method ?? "GET").toBe("GET");
    expect((init?.headers as Headers).get("x-organization-id")).toBe(
      "org-payments",
    );
  });

  it("POSTs only the opaque idempotency key with CSRF and organization context", async () => {
    document.cookie = "sbj_csrf=csrf-payment";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ booking_id: A }));
    await portalApi.initiatePayment(
      A,
      { idempotency_key: "opaque-attempt" },
      "org-payments",
    );
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/bookings/${A}/payment/initiate`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      idempotency_key: "opaque-attempt",
    });
    const headers = init?.headers as Headers;
    expect(headers.get("x-csrf-token")).toBe("csrf-payment");
    expect(headers.get("x-organization-id")).toBe("org-payments");
    expect(init?.credentials).toBe("same-origin");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe("portalApi — Phase 9.4.A customer offer reads", () => {
  const TRIP_ID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";
  it("GETs the exact same-origin path with org context and no CSRF/storage", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([]));
    await portalApi.listTripRequestOffers(TRIP_ID, "org-42");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/trip-requests/${TRIP_ID}/offers`);
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.cache).toBe("no-store");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
    expect((init?.headers as Headers).get("x-csrf-token")).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});

describe("portalApi — Phase 9.4.B customer offer selection", () => {
  it("POSTs the exact path with CSRF + org context and no request body", async () => {
    document.cookie = "sbj_csrf=csrf-value";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ id: "offer-id", status: "SELECTED" }),
      );
    await portalApi.selectOffer("trip-id", "offer-id", "org-42");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(
      "/api/proxy/trip-requests/trip-id/offers/offer-id/select",
    );
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
    expect((init?.headers as Headers).get("content-type")).toBeNull();
    expect((init?.headers as Headers).get("x-csrf-token")).toBe("csrf-value");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
  });
});

describe("portalApi — Phase 9.5.A customer Booking", () => {
  const TRIP_ID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";
  const OFFER_ID = "11111111-2222-4333-8444-555555555555";

  it("POSTs only trip_request_id and operator_offer_id with CSRF + org context", async () => {
    document.cookie = "sbj_csrf=csrf-value";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ status: "PENDING_OPERATOR_CONFIRMATION" }, 201),
      );
    await portalApi.createBooking(
      { trip_request_id: TRIP_ID, operator_offer_id: OFFER_ID },
      "org-42",
    );
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe("/api/proxy/bookings");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      trip_request_id: TRIP_ID,
      operator_offer_id: OFFER_ID,
    });
    expect(String(init?.body)).not.toMatch(
      /customer_id|operator_id|aircraft_id/,
    );
    expect((init?.headers as Headers).get("x-csrf-token")).toBe("csrf-value");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.cache).toBe("no-store");
  });

  it("GETs the exact trip-scoped authoritative Booking without CSRF", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ id: "booking" }));
    await portalApi.getTripRequestBooking(TRIP_ID, "org-42");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/trip-requests/${TRIP_ID}/booking`);
    expect(init?.method ?? "GET").toBe("GET");
    expect((init?.headers as Headers).get("x-csrf-token")).toBeNull();
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
  });
});

describe("portalApi — Phase 9.3.B customer write journey", () => {
  const TRIP_ID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";

  beforeEach(() => {
    document.cookie = "sbj_csrf=csrf-value";
  });

  it("listAirports GETs the exact collection path (no query, no org header)", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([]));
    await portalApi.listAirports();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe("/api/proxy/airports");
    expect(init?.method ?? "GET").toBe("GET");
    expect((init?.headers as Headers).get("x-organization-id")).toBeNull();
  });

  it("createPassenger POSTs the exact path with CSRF + org header and NO customer_id", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ id: "p1" }, 201));
    await portalApi.createPassenger(
      { first_name: "Ada", last_name: "Byron" },
      "org-42",
    );
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe("/api/proxy/passengers");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    const headers = init?.headers as Headers;
    expect(headers.get("x-csrf-token")).toBe("csrf-value");
    expect(headers.get("x-organization-id")).toBe("org-42");
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect(body).toEqual({ first_name: "Ada", last_name: "Byron" });
    expect("customer_id" in body).toBe(false);
  });

  it("createTripRequest POSTs the exact path with the org header and NO customer_id", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ id: TRIP_ID, status: "DRAFT" }, 201),
      );
    await portalApi.createTripRequest(
      {
        legs: [
          {
            origin_airport_id: "a1",
            destination_airport_id: "a2",
            departure_at: "2027-01-01T10:00:00.000Z",
            passenger_count: 1,
          },
        ],
        passenger_ids: ["p1"],
        requirements: { ground_transport_requested: false },
      },
      "org-42",
    );
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe("/api/proxy/trip-requests");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect("customer_id" in body).toBe(false);
    expect(JSON.stringify(body)).not.toContain("customer_id");
    expect(body.passenger_ids).toEqual(["p1"]);
  });

  it("submitTripRequest POSTs the exact id/submit path with the returned version", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ id: TRIP_ID, status: "SUBMITTED", version: 2 }),
      );
    await portalApi.submitTripRequest(TRIP_ID, 1, "org-42");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/trip-requests/${TRIP_ID}/submit`);
    expect(init?.method).toBe("POST");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect(body).toEqual({ expected_version: 1 });
    expect("customer_id" in body).toBe(false);
  });

  it("cancelTripRequest POSTs the exact id/cancel path with expected_version and NO customer_id", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ id: TRIP_ID, status: "CANCELLED", version: 3 }),
      );
    const result = await portalApi.cancelTripRequest(TRIP_ID, 2, "org-42");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`/api/proxy/trip-requests/${TRIP_ID}/cancel`);
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect((init?.headers as Headers).get("x-organization-id")).toBe("org-42");
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect(body).toEqual({ expected_version: 2 });
    expect("customer_id" in body).toBe(false);
    // The updated TripRequest parses normally.
    expect(result).toMatchObject({ status: "CANCELLED", version: 3 });
  });

  it("cancelTripRequest does not write to browser storage", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ id: TRIP_ID, status: "CANCELLED", version: 3 }),
    );
    await portalApi.cancelTripRequest(TRIP_ID, 2, "org-42");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("never writes credentials or ids to browser storage on writes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(jsonResponse({ id: "p1" }, 201)),
    );
    await portalApi.createPassenger(
      { first_name: "Ada", last_name: "Byron" },
      "org-42",
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});
