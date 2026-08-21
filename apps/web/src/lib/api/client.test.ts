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
