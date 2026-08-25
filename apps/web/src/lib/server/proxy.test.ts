import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildResponseHeaders,
  buildUpstreamHeaders,
  buildUpstreamUrl,
  forwardToUpstream,
  validateProxyRequest,
} from "@/lib/server/proxy";

const UPSTREAM = "http://api.internal:8000";

beforeEach(() => {
  process.env.API_UPSTREAM_ORIGIN = UPSTREAM;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("validateProxyRequest — closed allow-list", () => {
  it("accepts an allow-listed path with a permitted method", () => {
    expect(validateProxyRequest(["auth", "me"], "GET")).toMatchObject({
      ok: true,
      path: "auth/me",
    });
    expect(validateProxyRequest(["me", "bookings"], "GET")).toMatchObject({
      ok: true,
    });
  });

  it("rejects a path that is not on the allow-list (no open proxy)", () => {
    expect(validateProxyRequest(["admin", "users"], "GET")).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(validateProxyRequest(["operators", "123"], "GET")).toMatchObject({
      ok: false,
    });
  });

  it("rejects a permitted path with a disallowed method", () => {
    expect(validateProxyRequest(["auth", "me"], "POST")).toMatchObject({
      ok: false,
      status: 405,
    });
    expect(validateProxyRequest(["me", "bookings"], "DELETE")).toMatchObject({
      ok: false,
    });
  });

  it("rejects path traversal, encoded separators, and empty segments", () => {
    expect(validateProxyRequest(["..", "auth", "me"], "GET")).toMatchObject({
      ok: false,
    });
    expect(validateProxyRequest(["auth", "..", "me"], "GET")).toMatchObject({
      ok: false,
    });
    expect(validateProxyRequest(["auth%2fme"], "GET")).toMatchObject({
      ok: false,
    });
    expect(validateProxyRequest([""], "GET")).toMatchObject({ ok: false });
    expect(validateProxyRequest([], "GET")).toMatchObject({ ok: false });
  });
});

describe("Phase 9.2.A auth account-entry routes — exact allow-list", () => {
  // Every newly allow-listed path (including the two-segment resend and reset/confirm)
  // forwards on POST, rejects other methods with 405, and no `auth/*` wildcard leaks.
  const routes: readonly (readonly string[])[] = [
    ["auth", "register"],
    ["auth", "verify-email"],
    ["auth", "verification", "resend"],
    ["auth", "password-reset"],
    ["auth", "password-reset", "confirm"],
  ];

  it("accepts POST for each new route", () => {
    for (const segments of routes) {
      expect(validateProxyRequest(segments, "POST")).toMatchObject({
        ok: true,
        path: segments.join("/"),
      });
    }
  });

  it("rejects non-POST methods with 405", () => {
    for (const segments of routes) {
      for (const method of ["GET", "PUT", "PATCH", "DELETE"]) {
        expect(validateProxyRequest(segments, method)).toMatchObject({
          ok: false,
          status: 405,
        });
      }
    }
  });

  it("does not allow a wildcard or unknown auth path (still 404)", () => {
    expect(
      validateProxyRequest(["auth", "anything-else"], "POST"),
    ).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(
      validateProxyRequest(["auth", "verification"], "POST"),
    ).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(
      validateProxyRequest(["auth", "verification%2fresend"], "POST"),
    ).toMatchObject({ ok: false });
  });
});

describe("Phase 9.3.A parameterized reads — closed pattern allow-list", () => {
  const UUID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";

  it("accepts GET on the two allow-listed {id} read families", () => {
    expect(validateProxyRequest(["trip-requests", UUID], "GET")).toMatchObject({
      ok: true,
      path: `trip-requests/${UUID}`,
    });
    expect(validateProxyRequest(["airports", UUID], "GET")).toMatchObject({
      ok: true,
      path: `airports/${UUID}`,
    });
  });

  it("rejects non-GET methods on the {id} reads with 405 (reads only, no mutation)", () => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      expect(
        validateProxyRequest(["trip-requests", UUID], method),
      ).toMatchObject({ ok: false, status: 405 });
      expect(validateProxyRequest(["airports", UUID], method)).toMatchObject({
        ok: false,
        status: 405,
      });
    }
  });

  it("rejects the collection path without an id (pattern needs exactly two segments)", () => {
    expect(validateProxyRequest(["trip-requests"], "GET")).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(validateProxyRequest(["airports"], "GET")).toMatchObject({
      ok: false,
      status: 404,
    });
  });

  it("rejects extra segments and known mutation sub-routes (no passthrough)", () => {
    // A trailing segment must not match — guards against reaching submit/cancel/offers.
    for (const extra of ["extra", "submit", "cancel", "offers", "booking"]) {
      expect(
        validateProxyRequest(["trip-requests", UUID, extra], "GET"),
      ).toMatchObject({ ok: false, status: 404 });
      expect(
        validateProxyRequest(["trip-requests", UUID, extra], "POST"),
      ).toMatchObject({ ok: false, status: 404 });
    }
  });

  it("rejects a non-UUID id (opaque garbage never reaches upstream)", () => {
    for (const bad of ["not-a-uuid", "123", "abc", `${UUID}x`]) {
      expect(validateProxyRequest(["trip-requests", bad], "GET")).toMatchObject(
        { ok: false, status: 404 },
      );
    }
  });

  it("rejects encoded separators, traversal, and empty id segments", () => {
    expect(
      validateProxyRequest(["trip-requests", `${UUID}%2f..`], "GET"),
    ).toMatchObject({ ok: false });
    expect(validateProxyRequest(["trip-requests", ".."], "GET")).toMatchObject({
      ok: false,
    });
    expect(validateProxyRequest(["trip-requests", ""], "GET")).toMatchObject({
      ok: false,
    });
    expect(
      validateProxyRequest(["trip-requests", "a%2fb"], "GET"),
    ).toMatchObject({ ok: false });
  });

  it("does not turn other {id} families into a passthrough or collide on prefixes", () => {
    // Only trip-requests and airports are parameterized; nothing else is.
    for (const family of [
      "bookings",
      "payments",
      "offers",
      "customers",
      "operators",
    ]) {
      expect(validateProxyRequest([family, UUID], "GET")).toMatchObject({
        ok: false,
        status: 404,
      });
    }
    // A prefix-similar family name must not match the trip-requests pattern.
    expect(
      validateProxyRequest(["trip-requests-x", UUID], "GET"),
    ).toMatchObject({ ok: false, status: 404 });
    expect(validateProxyRequest(["airportsx", UUID], "GET")).toMatchObject({
      ok: false,
      status: 404,
    });
  });
});

describe("buildUpstreamUrl — trusted host only", () => {
  it("builds the URL from the configured origin, not any request input", () => {
    expect(buildUpstreamUrl("auth/me", "")).toBe(`${UPSTREAM}/api/v1/auth/me`);
  });

  it("preserves the original query string", () => {
    expect(buildUpstreamUrl("me/bookings", "?limit=5&offset=10")).toBe(
      `${UPSTREAM}/api/v1/me/bookings?limit=5&offset=10`,
    );
  });
});

describe("buildUpstreamHeaders — closed forward list", () => {
  it("forwards only the session cookie, CSRF, org context, and negotiation headers", () => {
    const incoming = new Headers({
      cookie: "sbj_session=abc; sbj_csrf=xyz",
      "x-csrf-token": "xyz",
      "x-organization-id": "org-1",
      "content-type": "application/json",
      accept: "application/json",
      host: "evil.example.com",
      authorization: "Bearer leak",
      "x-forwarded-for": "1.2.3.4",
    });
    const out = buildUpstreamHeaders(incoming);
    expect(out.get("cookie")).toBe("sbj_session=abc; sbj_csrf=xyz");
    expect(out.get("x-csrf-token")).toBe("xyz");
    expect(out.get("x-organization-id")).toBe("org-1");
    // Never forwards the browser host or arbitrary/authorization headers.
    expect(out.get("host")).toBeNull();
    expect(out.get("authorization")).toBeNull();
    expect(out.get("x-forwarded-for")).toBeNull();
  });
});

describe("buildResponseHeaders — cookies relayed, never cached", () => {
  it("relays Set-Cookie and forces no-store", () => {
    const upstream = new Response(null, {
      headers: { "content-type": "application/json" },
    });
    upstream.headers.append("set-cookie", "sbj_session=new; Path=/; HttpOnly");
    upstream.headers.append("set-cookie", "sbj_csrf=tok; Path=/");
    const out = buildResponseHeaders(upstream);
    expect(out.get("content-type")).toBe("application/json");
    expect(out.get("cache-control")).toBe("no-store");
    const cookies = out.getSetCookie();
    expect(cookies).toHaveLength(2);
    expect(cookies[0]).toContain("sbj_session=new");
  });
});

describe("forwardToUpstream — status/body fidelity and no leakage", () => {
  it("preserves distinct upstream status codes (never collapses to 200)", async () => {
    for (const status of [401, 403, 404, 409, 422, 429, 500]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify({ error: { code: "x", message: "y" } }), {
          status,
          headers: { "content-type": "application/json" },
        }),
      );
      const request = new Request("http://portal.local/api/proxy/auth/me");
      const response = await forwardToUpstream(request, "auth/me");
      expect(response.status).toBe(status);
    }
  });

  it("returns a typed 502 when the upstream is unreachable, without leaking details", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new Error("ECONNREFUSED secret-host"),
    );
    const request = new Request("http://portal.local/api/proxy/auth/me");
    const response = await forwardToUpstream(request, "auth/me");
    expect(response.status).toBe(502);
    const body = (await response.json()) as {
      error: { code: string; message: string };
    };
    expect(body.error.code).toBe("upstream_unavailable");
    expect(body.error.message).not.toContain("secret-host");
  });

  it("forwards the request body and never logs cookies/tokens", async () => {
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 201 }));
    const request = new Request("http://portal.local/api/proxy/auth/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie: "sbj_session=secret-session",
        "x-csrf-token": "secret-csrf",
      },
      body: JSON.stringify({ email: "a@b.co", password: "p" }),
    });
    const response = await forwardToUpstream(request, "auth/login");
    expect(response.status).toBe(201);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init?.body).toBe(JSON.stringify({ email: "a@b.co", password: "p" }));
    const logged = [...logSpy.mock.calls, ...errorSpy.mock.calls]
      .flat()
      .join(" ");
    expect(logged).not.toContain("secret-session");
    expect(logged).not.toContain("secret-csrf");
  });
});
