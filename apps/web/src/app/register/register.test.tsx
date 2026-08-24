import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm } from "@/app/register/RegisterForm";
import { ApiError } from "@/lib/api/errors";

const register = vi.fn();
const resendVerification = vi.fn();

vi.mock("@/lib/api/client", () => ({
  portalApi: {
    register: (...args: unknown[]) => register(...args),
    resendVerification: (...args: unknown[]) => resendVerification(...args),
  },
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const VALID_PASSWORD = "CorrectHorse12";

function fill(email: string, password: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: confirm },
  });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Create account" }));
}

beforeEach(() => {
  register.mockReset();
  resendVerification.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RegisterForm — fields & accessibility", () => {
  it("renders email, password, confirm with correct labels, types, and autocomplete", () => {
    render(<RegisterForm />);
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    const confirm = screen.getByLabelText(
      "Confirm password",
    ) as HTMLInputElement;
    expect(email.type).toBe("email");
    expect(email.getAttribute("autocomplete")).toBe("email");
    expect(password.type).toBe("password");
    expect(password.getAttribute("autocomplete")).toBe("new-password");
    expect(confirm.getAttribute("autocomplete")).toBe("new-password");
    // Password hint is associated for screen readers.
    expect(password.getAttribute("aria-describedby")).toBe(
      "register-password-hint",
    );
    expect(
      screen.getByText(
        "At least 12 characters, including upper- and lower-case letters.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Create your account" }),
    ).toBeTruthy();
  });
});

describe("RegisterForm — client validation", () => {
  it("rejects a password that does not meet the rule without calling the API", () => {
    render(<RegisterForm />);
    fill("a@b.co", "short", "short");
    submit();
    expect(register).not.toHaveBeenCalled();
    expect(
      screen.getByText("Check your email and password and try again."),
    ).toBeTruthy();
  });

  it("rejects mismatched passwords without calling the API", () => {
    render(<RegisterForm />);
    fill("a@b.co", VALID_PASSWORD, "DifferentPass34");
    submit();
    expect(register).not.toHaveBeenCalled();
    expect(screen.getByText("Passwords do not match.")).toBeTruthy();
  });
});

describe("RegisterForm — submission", () => {
  it("calls register with exactly email+password (confirm is never sent) and shows success", async () => {
    register.mockResolvedValueOnce({
      user: { id: "1", email: "a@b.co" },
      verification_token: "DEV-TOKEN-should-never-render",
    });
    render(<RegisterForm />);
    fill("a@b.co", VALID_PASSWORD, VALID_PASSWORD);
    submit();

    await screen.findByRole("heading", { name: "Check your email" });
    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith("a@b.co", VALID_PASSWORD);
    // Confirm password was never passed.
    expect(register.mock.calls[0]).toHaveLength(2);
    // The dev verification_token must never reach the DOM.
    expect(document.body.textContent).not.toContain(
      "DEV-TOKEN-should-never-render",
    );
    // No client-side persistence of anything.
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("disables submit while pending and prevents a double submit", async () => {
    let resolve: (value: unknown) => void = () => {};
    register.mockImplementationOnce(() => new Promise((r) => (resolve = r)));
    render(<RegisterForm />);
    fill("a@b.co", VALID_PASSWORD, VALID_PASSWORD);
    const button = screen.getByRole("button", { name: "Create account" });
    fireEvent.click(button);
    // Now pending: button shows busy label and is disabled.
    const pending = screen.getByRole("button", { name: "Creating account…" });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(pending);
    resolve({ user: { id: "1" }, verification_token: null });
    await screen.findByRole("heading", { name: "Check your email" });
    expect(register).toHaveBeenCalledTimes(1);
  });
});

describe("RegisterForm — error mapping", () => {
  const cases: Array<[ApiError | Error, string]> = [
    [
      new ApiError(409, "email_already_registered", "x", "conflict"),
      "An account with this email may already exist. Try signing in.",
    ],
    [
      new ApiError(429, "rate_limited", "x", "rate_limited"),
      "Too many registration attempts. Please wait and try again.",
    ],
    [
      new ApiError(400, "iam_error", "x", "client"),
      "Check your email and password and try again.",
    ],
    [
      new Error("network down"),
      "We couldn't create your account right now. Please try again.",
    ],
  ];

  for (const [thrown, message] of cases) {
    it(`maps ${thrown instanceof ApiError ? thrown.kind : "unknown"} to safe copy`, async () => {
      register.mockRejectedValueOnce(thrown);
      render(<RegisterForm />);
      fill("a@b.co", VALID_PASSWORD, VALID_PASSWORD);
      submit();
      await screen.findByText(message);
      // Raw backend text is never surfaced.
      expect(document.body.textContent).not.toContain("iam_error");
    });
  }
});

describe("RegisterForm — resend from success state", () => {
  async function reachSuccess() {
    register.mockResolvedValueOnce({
      user: { id: "1" },
      verification_token: null,
    });
    render(<RegisterForm />);
    fill("person@example.com", VALID_PASSWORD, VALID_PASSWORD);
    submit();
    await screen.findByRole("heading", { name: "Check your email" });
  }

  it("resends using the registered email and shows a uniform acknowledgement", async () => {
    await reachSuccess();
    resendVerification.mockResolvedValueOnce({ message: "ok" });
    fireEvent.click(
      screen.getByRole("button", { name: "Resend verification email" }),
    );
    await screen.findByText(
      "If the account requires verification, we've sent new instructions.",
    );
    expect(resendVerification).toHaveBeenCalledWith("person@example.com");
  });

  it("handles 429 on resend without revealing account state", async () => {
    await reachSuccess();
    resendVerification.mockRejectedValueOnce(
      new ApiError(429, "rate_limited", "x", "rate_limited"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Resend verification email" }),
    );
    await screen.findByText(
      "Please wait a moment before requesting another email.",
    );
    // No token or account detail leaked.
    expect(document.body.textContent).not.toMatch(/token/i);
  });

  it("prevents overlapping resend submits", async () => {
    await reachSuccess();
    resendVerification.mockImplementationOnce(() => new Promise(() => {}));
    const button = screen.getByRole("button", {
      name: "Resend verification email",
    });
    fireEvent.click(button);
    const sending = screen.getByRole("button", { name: "Sending…" });
    expect((sending as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(sending);
    await waitFor(() => expect(resendVerification).toHaveBeenCalledTimes(1));
  });
});
