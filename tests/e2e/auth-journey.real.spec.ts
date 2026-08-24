import { expect, test } from "@playwright/test";

/**
 * Phase 9.2.B2.3 — LOCAL, OPT-IN real customer-auth journey.
 *
 * This spec sends and consumes a REAL verification email (real Resend quota) and is therefore
 * NEVER run in CI (CI runs no Playwright e2e) and NEVER against a deployed environment. It is
 * DOUBLE-GATED: it skips unless BOTH `RUN_REAL_AUTH_E2E=1` and `AUTH_EMAIL_ENABLED=true` are
 * set. `AUTH_EMAIL_ENABLED=true` is permitted only for this deliberate localhost run — the B1
 * resend timing side-channel remains a production gate.
 *
 * The verification token is stored HASHED at rest and never logged, so it cannot be recovered
 * from the database. The operator opens the delivered email and supplies the full
 * `/verify-email#token=...` link via `SBJ_E2E_VERIFICATION_URL`. Credentials come from
 * `SBJ_E2E_TEST_EMAIL` / `SBJ_E2E_PASSWORD` and are never committed.
 *
 * PRECONDITION (see the runbook): the operator has already registered the account at
 * `/register` and received the verification email. This spec deliberately does NOT re-register
 * — a second registration for the same pending account could rotate the token and invalidate
 * the supplied link. It exercises the security-critical consumption half of the journey:
 * verify (fragment strip-before-POST) → login → real `/portal` → logout → lockout. The
 * registration half (enumeration-safe ack, no auto-login) is covered by the web unit suite.
 */

const enabled =
  process.env.RUN_REAL_AUTH_E2E === "1" &&
  process.env.AUTH_EMAIL_ENABLED === "true";

const EMAIL = process.env.SBJ_E2E_TEST_EMAIL ?? "";
const PASSWORD = process.env.SBJ_E2E_PASSWORD ?? "";
const VERIFICATION_URL = process.env.SBJ_E2E_VERIFICATION_URL ?? "";

test.describe("real customer auth journey (opt-in, local only)", () => {
  test.skip(
    !enabled,
    "set RUN_REAL_AUTH_E2E=1 and AUTH_EMAIL_ENABLED=true to run the real local E2E",
  );

  test("verify (fragment-stripped) → login → portal → logout", async ({
    page,
  }) => {
    expect(EMAIL, "SBJ_E2E_TEST_EMAIL is required").not.toBe("");
    expect(PASSWORD, "SBJ_E2E_PASSWORD is required").not.toBe("");

    // 1. Manual bridge: operator supplies the emailed verification link (from the prior,
    //    already-completed registration — see the runbook precondition above).
    expect(
      VERIFICATION_URL,
      "SBJ_E2E_VERIFICATION_URL (the emailed /verify-email#token=... link) is required",
    ).toMatch(/\/verify-email#token=[A-Za-z0-9_-]+$/);

    // 2. Fresh full-page load of the verification link. The client strips the fragment via
    //    replaceState BEFORE the verify POST, so the token must never survive in the URL/DOM.
    const rawToken = VERIFICATION_URL.split("#token=")[1] ?? "__none__";
    await page.goto(VERIFICATION_URL);
    await expect(
      page.getByRole("heading", { name: "Your email is verified" }),
    ).toBeVisible();
    const leak = await page.evaluate((tok) => {
      const html = document.documentElement.outerHTML;
      return {
        hash: window.location.hash,
        href: window.location.href,
        inDom: document.body.innerText.includes(tok),
        inHtml: html.includes(tok),
        ls: localStorage.length,
        ss: sessionStorage.length,
        cookie: document.cookie,
      };
    }, rawToken);
    expect(leak.hash).toBe("");
    expect(leak.href).not.toContain("#");
    expect(leak.href).not.toContain(rawToken);
    expect(leak.inDom).toBe(false);
    expect(leak.inHtml).toBe(false);
    expect(leak.ls).toBe(0);
    expect(leak.ss).toBe(0);
    expect(leak.cookie).toBe("");

    // 3. Follow the CTA to the verified-login banner, then sign in.
    await page.getByRole("link", { name: "Continue to sign in" }).click();
    await expect(page).toHaveURL(/\/login\?verified=1$/);
    await expect(
      page.getByText("Your email is verified. Sign in to continue."),
    ).toBeVisible();
    await page.getByLabel("Email").fill(EMAIL);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    // 4. Real /portal, HttpOnly session (JS sees only the csrf cookie), customer org context.
    await expect(page).toHaveURL(/\/portal$/);
    const cookie = await page.evaluate(() => document.cookie);
    expect(cookie).not.toContain("sbj_session");
    const me = await page.evaluate(async () => {
      const r = await fetch("/api/proxy/auth/me", { credentials: "include" });
      return { status: r.status, body: await r.json() };
    });
    expect(me.status).toBe(200);
    expect(me.body.user.email).toBe(EMAIL);
    expect(me.body.user.status).toBe("ACTIVE");
    expect(me.body.memberships).toHaveLength(1);
    expect(me.body.memberships[0].organization_type).toBe("CUSTOMER");
    expect(me.body.memberships[0].role).toBe("CUSTOMER_OWNER");

    // 5. Real logout revokes the session; protected access is lost.
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
    const afterLogout = await page.evaluate(async () => {
      const r = await fetch("/api/proxy/auth/me", { credentials: "include" });
      return r.status;
    });
    expect(afterLogout).toBe(401);
    await page.goto("/portal");
    await expect(page).toHaveURL(/\/login\?next=%2Fportal/);
  });
});
