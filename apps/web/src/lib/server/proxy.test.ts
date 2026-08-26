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

describe("Phase 9.4.A offer reads — exact closed pattern", () => {
  const UUID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";
  it("allows only GET on the exact trip offer collection", () => {
    expect(
      validateProxyRequest(["trip-requests", UUID, "offers"], "GET"),
    ).toMatchObject({ ok: true, path: `trip-requests/${UUID}/offers` });
    for (const method of ["POST", "PUT", "PATCH", "DELETE"])
      expect(
        validateProxyRequest(["trip-requests", UUID, "offers"], method),
      ).toMatchObject({ ok: false, status: 405 });
  });
  it("rejects malformed, extended, mutation, encoded, and adjacent families", () => {
    const rejected = [
      ["trip-requests", "not-a-uuid", "offers"],
      ["trip-requests", UUID, "offers", UUID],
      ["trip-requests", UUID, "offers%2fanything"],
      ["trip-requests", UUID, "offers%5canything"],
      ["trip-requests", "..", "offers"],
      ["trip-requests-extra", UUID, "offers"],
      ["offers"],
      ["payments"],
    ];
    for (const segments of rejected)
      expect(validateProxyRequest(segments, "GET")).toMatchObject({
        ok: false,
        status: 404,
      });
  });
});

describe("Phase 9.4.B offer selection — exact closed pattern", () => {
  const TRIP = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";
  const OFFER = "11111111-2222-4333-8444-555555555555";
  it("allows only POST on the exact selection path", () => {
    const path = ["trip-requests", TRIP, "offers", OFFER, "select"];
    expect(validateProxyRequest(path, "POST")).toMatchObject({
      ok: true,
      path: path.join("/"),
    });
    for (const method of ["GET", "PUT", "PATCH", "DELETE"])
      expect(validateProxyRequest(path, method)).toMatchObject({
        ok: false,
        status: 405,
      });
  });
  it("rejects malformed UUIDs, extra segments, and adjacent offer mutations", () => {
    for (const path of [
      ["trip-requests", "bad", "offers", OFFER, "select"],
      ["trip-requests", TRIP, "offers", "bad", "select"],
      ["trip-requests", TRIP, "offers", OFFER, "select", "extra"],
      ["trip-requests", TRIP, "offers", OFFER, "withdraw"],
      ["trip-requests", TRIP, "offers", OFFER],
    ])
      expect(validateProxyRequest(path, "POST")).toMatchObject({
        ok: false,
        status: 404,
      });
  });
});

describe("Phase 9.5.A Booking routes — minimum closed surface", () => {
  const TRIP = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";
  const BOOKING = "11111111-2222-4333-8444-555555555555";

  it("allows only POST on the exact Booking collection", () => {
    expect(validateProxyRequest(["bookings"], "POST")).toMatchObject({
      ok: true,
      path: "bookings",
    });
    for (const method of ["GET", "PUT", "PATCH", "DELETE"])
      expect(validateProxyRequest(["bookings"], method)).toMatchObject({
        ok: false,
        status: 405,
      });
  });

  it("allows only GET on the exact trip-scoped Booking read", () => {
    const path = ["trip-requests", TRIP, "booking"];
    expect(validateProxyRequest(path, "GET")).toMatchObject({
      ok: true,
      path: path.join("/"),
    });
    for (const method of ["POST", "PUT", "PATCH", "DELETE"])
      expect(validateProxyRequest(path, method)).toMatchObject({
        ok: false,
        status: 405,
      });
  });

  it("keeps detail, cancellation, and payment closed", () => {
    for (const [path, method] of [
      [["bookings", BOOKING], "GET"],
      [["bookings", BOOKING, "cancel"], "POST"],
      [["bookings", BOOKING, "payment"], "POST"],
      [["trip-requests", "not-a-uuid", "booking"], "GET"],
      [["trip-requests", TRIP, "booking", "extra"], "GET"],
      [["trip-requests", "..", "booking"], "GET"],
      [["trip-requests", `${TRIP}%2fextra`, "booking"], "GET"],
    ] as const)
      expect(validateProxyRequest([...path], method)).toMatchObject({
        ok: false,
        status: 404,
      });
  });
});

describe("Phase 9.5.B operator decisions — exact closed surface", () => {
  const BOOKING = "11111111-2222-4333-8444-555555555555";
  it("allows only the queue GET and exact decision POSTs", () => {
    expect(
      validateProxyRequest(["me", "operator-bookings"], "GET"),
    ).toMatchObject({ ok: true });
    for (const action of ["confirm", "reject"])
      expect(
        validateProxyRequest(["bookings", BOOKING, action], "POST"),
      ).toMatchObject({ ok: true });
  });
  it("keeps cancellation, payment, malformed and adjacent routes closed", () => {
    for (const [path, method] of [
      [["me", "operator-bookings"], "POST"],
      [["bookings", BOOKING, "confirm"], "GET"],
      [["bookings", BOOKING, "cancel"], "POST"],
      [["bookings", BOOKING, "payment"], "POST"],
      [["bookings", "bad", "confirm"], "POST"],
      [["bookings", BOOKING, "reject", "extra"], "POST"],
      [["operators", BOOKING, "bookings"], "GET"],
    ] as const)
      expect(validateProxyRequest([...path], method)).toMatchObject({
        ok: false,
      });
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

  it("does not serve a {id} read via the one-segment collection path", () => {
    // The two-segment {id} GET pattern never matches a bare collection. Since Phase 9.3.B the
    // collections have their OWN exact entries (trip-requests POST-only → GET is 405; airports
    // GET → allowed), so a bare collection is governed by that entry, not the read pattern.
    expect(validateProxyRequest(["trip-requests"], "GET")).toMatchObject({
      ok: false,
      status: 405,
    });
    expect(validateProxyRequest(["airports"], "GET")).toMatchObject({
      ok: true,
      path: "airports",
    });
  });

  it("rejects extra segments and unexposed mutation sub-routes (no passthrough)", () => {
    // A trailing segment must not widen the {id} GET into a passthrough. `submit` (9.3.B) and
    // `cancel` (9.3.C) and offers (9.4.A GET-only) are covered separately; unknowns stay 404.
    for (const extra of ["extra"]) {
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

describe("Phase 9.3.B customer write routes — closed allow-list", () => {
  const UUID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";

  it("accepts the exact create mutations (POST passengers, POST trip-requests)", () => {
    expect(validateProxyRequest(["passengers"], "POST")).toMatchObject({
      ok: true,
      path: "passengers",
    });
    expect(validateProxyRequest(["trip-requests"], "POST")).toMatchObject({
      ok: true,
      path: "trip-requests",
    });
  });

  it("accepts POST submit on a valid UUID (the one parameterized mutation)", () => {
    expect(
      validateProxyRequest(["trip-requests", UUID, "submit"], "POST"),
    ).toMatchObject({ ok: true, path: `trip-requests/${UUID}/submit` });
  });

  it("accepts the airports collection GET (picker source)", () => {
    expect(validateProxyRequest(["airports"], "GET")).toMatchObject({
      ok: true,
      path: "airports",
    });
  });

  it("rejects wrong methods on the create mutations with 405", () => {
    for (const method of ["GET", "PUT", "PATCH", "DELETE"]) {
      expect(validateProxyRequest(["passengers"], method)).toMatchObject({
        ok: false,
        status: 405,
      });
      expect(validateProxyRequest(["trip-requests"], method)).toMatchObject({
        ok: false,
        status: 405,
      });
    }
    // airports collection is read-only.
    expect(validateProxyRequest(["airports"], "POST")).toMatchObject({
      ok: false,
      status: 405,
    });
  });

  it("rejects wrong methods on submit with 405 (POST-only)", () => {
    for (const method of ["GET", "PUT", "PATCH", "DELETE"]) {
      expect(
        validateProxyRequest(["trip-requests", UUID, "submit"], method),
      ).toMatchObject({ ok: false, status: 405 });
    }
  });

  it("keeps offer writes closed and rejects every other trip sub-route", () => {
    // `cancel` became a dedicated Phase 9.3.C POST route (covered separately); everything
    // else under a trip stays fully unlisted (404 on any method).
    expect(
      validateProxyRequest(["trip-requests", UUID, "offers"], "POST"),
    ).toMatchObject({ ok: false, status: 405 });
    expect(
      validateProxyRequest(["trip-requests", UUID, "offers"], "GET"),
    ).toMatchObject({ ok: true });
    expect(
      validateProxyRequest(["trip-requests", UUID, "booking"], "GET"),
    ).toMatchObject({ ok: true });
    expect(
      validateProxyRequest(["trip-requests", UUID, "booking"], "POST"),
    ).toMatchObject({ ok: false, status: 405 });
    for (const sub of ["quotes", "documents"]) {
      expect(
        validateProxyRequest(["trip-requests", UUID, sub], "POST"),
      ).toMatchObject({ ok: false, status: 404 });
      expect(
        validateProxyRequest(["trip-requests", UUID, sub], "GET"),
      ).toMatchObject({ ok: false, status: 404 });
    }
  });

  it("rejects an extra segment after submit (no prefix widening)", () => {
    expect(
      validateProxyRequest(["trip-requests", UUID, "submit", "extra"], "POST"),
    ).toMatchObject({ ok: false, status: 404 });
  });

  it("rejects submit on a non-UUID id", () => {
    for (const bad of ["not-a-uuid", "123", `${UUID}x`]) {
      expect(
        validateProxyRequest(["trip-requests", bad, "submit"], "POST"),
      ).toMatchObject({ ok: false, status: 404 });
    }
  });

  it("rejects a POST under passengers/<anything> (no passenger sub-routes)", () => {
    expect(validateProxyRequest(["passengers", UUID], "POST")).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(validateProxyRequest(["passengers", "roster"], "GET")).toMatchObject(
      {
        ok: false,
        status: 404,
      },
    );
  });

  it("rejects encoded slash/backslash, dot, dot-dot and encoded traversal on submit", () => {
    for (const bad of [
      `${UUID}%2f..`,
      `${UUID}%5c..`,
      ".",
      "..",
      "%2e%2e",
      `${UUID}%2fsubmit`,
    ]) {
      expect(
        validateProxyRequest(["trip-requests", bad, "submit"], "POST"),
      ).toMatchObject({ ok: false });
    }
  });

  it("does not collide on prefix-similar families for the new routes", () => {
    expect(validateProxyRequest(["passengers-x"], "POST")).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(validateProxyRequest(["trip-requests-x"], "POST")).toMatchObject({
      ok: false,
      status: 404,
    });
    expect(validateProxyRequest(["airportsx"], "GET")).toMatchObject({
      ok: false,
      status: 404,
    });
  });
});

describe("Phase 9.3.C cancel route — closed pattern allow-list", () => {
  const UUID = "b32413c8-88e9-4c05-89e5-78afb14f5eb4";

  it("accepts POST cancel on a valid UUID", () => {
    expect(
      validateProxyRequest(["trip-requests", UUID, "cancel"], "POST"),
    ).toMatchObject({ ok: true, path: `trip-requests/${UUID}/cancel` });
  });

  it("keeps POST submit allowed (unchanged)", () => {
    expect(
      validateProxyRequest(["trip-requests", UUID, "submit"], "POST"),
    ).toMatchObject({ ok: true });
  });

  it("rejects wrong methods on cancel with 405 (POST-only)", () => {
    for (const method of ["GET", "PUT", "PATCH", "DELETE"]) {
      expect(
        validateProxyRequest(["trip-requests", UUID, "cancel"], method),
      ).toMatchObject({ ok: false, status: 405 });
    }
  });

  it("rejects offers / booking and an extra segment after cancel (404)", () => {
    expect(
      validateProxyRequest(["trip-requests", UUID, "offers"], "POST"),
    ).toMatchObject({ ok: false, status: 405 });
    expect(
      validateProxyRequest(["trip-requests", UUID, "booking"], "POST"),
    ).toMatchObject({ ok: false, status: 405 });
    for (const extra of ["extra", "foo"]) {
      expect(
        validateProxyRequest(["trip-requests", UUID, "cancel", extra], "POST"),
      ).toMatchObject({ ok: false, status: 404 });
    }
  });

  it("rejects a non-UUID cancel id and encoded separators/traversal", () => {
    for (const bad of ["not-a-uuid", `${UUID}x`]) {
      expect(
        validateProxyRequest(["trip-requests", bad, "cancel"], "POST"),
      ).toMatchObject({ ok: false, status: 404 });
    }
    for (const bad of [`${UUID}%2f..`, `${UUID}%5c..`, "..", "%2e%2e"]) {
      expect(
        validateProxyRequest(["trip-requests", bad, "cancel"], "POST"),
      ).toMatchObject({ ok: false });
    }
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
