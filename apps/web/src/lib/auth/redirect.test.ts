import { describe, expect, it } from "vitest";

import {
  buildLoginRedirect,
  returnPathFromSearch,
  sanitizeReturnPath,
} from "@/lib/auth/redirect";

describe("sanitizeReturnPath", () => {
  it("keeps a safe same-origin absolute path (with query and hash)", () => {
    expect(sanitizeReturnPath("/portal/bookings")).toBe("/portal/bookings");
    expect(sanitizeReturnPath("/portal/bookings?tab=past#top")).toBe(
      "/portal/bookings?tab=past#top",
    );
    expect(sanitizeReturnPath("/portal/my-bookings")).toBe(
      "/portal/my-bookings",
    );
  });

  it("rejects absolute URLs and external hosts", () => {
    expect(sanitizeReturnPath("http://evil.com/x")).toBe("/portal");
    expect(sanitizeReturnPath("https://evil.com")).toBe("/portal");
  });

  it("rejects protocol-relative and backslash tricks", () => {
    expect(sanitizeReturnPath("//evil.com")).toBe("/portal");
    expect(sanitizeReturnPath("/\\evil.com")).toBe("/portal");
    expect(sanitizeReturnPath("/portal\\..\\evil")).toBe("/portal");
  });

  it("rejects control characters (CR/LF header injection)", () => {
    expect(sanitizeReturnPath("/portal\r\nSet-Cookie: x=y")).toBe("/portal");
    expect(sanitizeReturnPath("/portal\nnext")).toBe("/portal");
  });

  it("rejects non-absolute, empty, and nullish values", () => {
    expect(sanitizeReturnPath("portal")).toBe("/portal");
    expect(sanitizeReturnPath("")).toBe("/portal");
    expect(sanitizeReturnPath(null)).toBe("/portal");
    expect(sanitizeReturnPath(undefined)).toBe("/portal");
  });

  it("never returns the login page itself (avoids a redirect loop)", () => {
    expect(sanitizeReturnPath("/login")).toBe("/portal");
    expect(sanitizeReturnPath("/login?next=/portal")).toBe("/portal");
  });

  it("honours a custom fallback", () => {
    expect(sanitizeReturnPath("http://evil.com", "/portal/account")).toBe(
      "/portal/account",
    );
  });
});

describe("buildLoginRedirect / returnPathFromSearch", () => {
  it("builds a login URL carrying the sanitized return path", () => {
    expect(buildLoginRedirect("/portal/bookings")).toBe(
      "/login?next=%2Fportal%2Fbookings",
    );
    // An unsafe current path collapses to the default.
    expect(buildLoginRedirect("http://evil.com")).toBe("/login?next=%2Fportal");
  });

  it("reads and sanitizes the return path from search params", () => {
    expect(
      returnPathFromSearch(new URLSearchParams("next=/portal/account")),
    ).toBe("/portal/account");
    expect(returnPathFromSearch(new URLSearchParams("next=//evil.com"))).toBe(
      "/portal",
    );
  });
});
