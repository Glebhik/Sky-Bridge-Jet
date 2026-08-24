import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  VerifyEmailClient,
  readTokenFromHash,
} from "@/app/verify-email/VerifyEmailClient";
import { ApiError } from "@/lib/api/errors";

const verifyEmail = vi.fn();
const resendVerification = vi.fn();

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    verifyEmail: (...args: unknown[]) => verifyEmail(...args),
    resendVerification: (...args: unknown[]) => resendVerification(...args),
  },
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const TOKEN = "abcDEF123_the-URLsafe-token";

function setHash(hash: string) {
  window.location.hash = hash;
}

beforeEach(() => {
  verifyEmail.mockReset();
  resendVerification.mockReset();
  window.location.hash = "";
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.location.hash = "";
});

describe("readTokenFromHash — strict parsing", () => {
  it("accepts exactly #token=<url-safe value>", () => {
    expect(readTokenFromHash(`#token=${TOKEN}`)).toBe(TOKEN);
  });
  it("rejects missing/empty/wrong-key/multiple/malformed fragments", () => {
    expect(readTokenFromHash("")).toBeNull();
    expect(readTokenFromHash("#")).toBeNull();
    expect(readTokenFromHash("#token=")).toBeNull();
    expect(readTokenFromHash("#code=abc")).toBeNull();
    expect(readTokenFromHash("#token=a&token=b")).toBeNull();
    expect(readTokenFromHash("#token=a&x=y")).toBeNull();
    expect(readTokenFromHash("#token=has space")).toBeNull();
    expect(readTokenFromHash("#token=has%2Fslash")).toBeNull();
  });
});

describe("VerifyEmailClient — token security", () => {
  it("strips the fragment (replaceState) BEFORE the verify request, with no '#' in the URL", async () => {
    const order: string[] = [];
    const replaceSpy = vi
      .spyOn(window.history, "replaceState")
      .mockImplementation((_s, _t, url) => {
        order.push(`replaceState:${String(url)}`);
      });
    verifyEmail.mockImplementation((token: string) => {
      order.push(`verify:${token}`);
      return Promise.resolve({ id: "1", status: "ACTIVE" });
    });
    setHash(`#token=${TOKEN}`);

    render(<VerifyEmailClient />);
    await screen.findByRole("heading", { name: "Your email is verified" });

    // replaceState happened first, and it targeted a URL WITHOUT a fragment.
    expect(order[0]).toMatch(/^replaceState:/);
    expect(order[1]).toBe(`verify:${TOKEN}`);
    expect(order[0]).not.toContain("#");
    expect(replaceSpy).toHaveBeenCalledTimes(1);
    // Token is passed to the API but never rendered.
    expect(verifyEmail).toHaveBeenCalledWith(TOKEN);
    expect(document.body.textContent).not.toContain(TOKEN);
    // No client-side persistence of the token.
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("shows missing_token and never calls verify for a wrong/empty fragment", async () => {
    setHash("#code=nope");
    render(<VerifyEmailClient />);
    await screen.findByRole("heading", {
      name: "Verification link unavailable",
    });
    expect(verifyEmail).not.toHaveBeenCalled();
  });
});

describe("VerifyEmailClient — state machine", () => {
  it("verified → CTA links to /login?verified=1", async () => {
    verifyEmail.mockResolvedValueOnce({ id: "1", status: "ACTIVE" });
    setHash(`#token=${TOKEN}`);
    render(<VerifyEmailClient />);
    const cta = await screen.findByRole("link", {
      name: "Continue to sign in",
    });
    expect(cta.getAttribute("href")).toBe("/login?verified=1");
  });

  it("400 invalid_token → invalid_or_expired, offers a resend, no token shown", async () => {
    verifyEmail.mockRejectedValueOnce(
      new ApiError(400, "invalid_token", "x", "client"),
    );
    setHash(`#token=${TOKEN}`);
    render(<VerifyEmailClient />);
    await screen.findByRole("heading", {
      name: "This verification link can't be used",
    });
    expect(screen.getByLabelText("Email")).toBeTruthy(); // resend form present
    expect(document.body.textContent).not.toContain(TOKEN);
    expect(document.body.textContent).not.toContain("invalid_token");
  });

  it("network failure → retry re-attempts with the same token and can succeed", async () => {
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
    verifyEmail
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ id: "1", status: "ACTIVE" });
    setHash(`#token=${TOKEN}`);
    render(<VerifyEmailClient />);

    await screen.findByRole("heading", {
      name: "We couldn't verify your email",
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry verification" }));
    await screen.findByRole("heading", { name: "Your email is verified" });
    expect(verifyEmail).toHaveBeenCalledTimes(2);
    expect(verifyEmail).toHaveBeenNthCalledWith(2, TOKEN);
  });
});

describe("ResendVerificationForm — via invalid state", () => {
  it("posts the entered email and shows a uniform acknowledgement", async () => {
    verifyEmail.mockRejectedValueOnce(
      new ApiError(400, "invalid_token", "x", "client"),
    );
    setHash(`#token=${TOKEN}`);
    render(<VerifyEmailClient />);
    await screen.findByRole("heading", {
      name: "This verification link can't be used",
    });

    resendVerification.mockResolvedValueOnce({ message: "ok" });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "person@example.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send a new verification email" }),
    );
    await screen.findByText(
      "If the account requires verification, we've sent new instructions.",
    );
    expect(resendVerification).toHaveBeenCalledWith("person@example.com");
  });

  it("handles 429 on resend neutrally and prevents overlapping submits", async () => {
    verifyEmail.mockRejectedValueOnce(
      new ApiError(400, "invalid_token", "x", "client"),
    );
    setHash(`#token=${TOKEN}`);
    render(<VerifyEmailClient />);
    await screen.findByRole("heading", {
      name: "This verification link can't be used",
    });

    resendVerification.mockRejectedValueOnce(
      new ApiError(429, "rate_limited", "x", "rate_limited"),
    );
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "person@example.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send a new verification email" }),
    );
    await screen.findByText(
      "Please wait a moment before requesting another email.",
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});
