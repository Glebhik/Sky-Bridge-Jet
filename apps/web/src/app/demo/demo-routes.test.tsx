import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DemoAccountPage from "@/app/demo/account/page";
import DemoBookingsPage from "@/app/demo/bookings/page";
import DemoLayout, { metadata as demoMetadata } from "@/app/demo/layout";
import DemoDashboardPage from "@/app/demo/page";
import DemoOffersPage from "@/app/demo/offers/page";
import { metadata as rootMetadata } from "@/app/layout";
import {
  DEMO_METADATA_DESCRIPTION,
  DEMO_METADATA_TITLE,
  DEMO_OFFER_INERT_LABEL,
  DEMO_OFFER_READ_ONLY_LABEL,
} from "@/lib/demo/copy";

let currentPath = "/demo";
const apiClientImported = vi.fn();
const sessionBootstrapImported = vi.fn();

vi.mock("@/lib/api/client", () => {
  apiClientImported();
  throw new Error(
    "The production typed API client must not enter demo routes.",
  );
});

vi.mock("@/lib/session/server", () => {
  sessionBootstrapImported();
  throw new Error(
    "The authenticated session bootstrap must not enter demo routes.",
  );
});

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  usePathname: () => currentPath,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

function renderEnabledRoute(path: string, page: ReactNode) {
  process.env.DEMO_PORTAL_ENABLED = "true";
  currentPath = path;
  return render(<>{DemoLayout({ children: page })}</>);
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  apiClientImported.mockClear();
  sessionBootstrapImported.mockClear();
});

afterEach(() => {
  delete process.env.DEMO_PORTAL_ENABLED;
  vi.unstubAllGlobals();
});

describe("public demonstration route family", () => {
  it("returns not found when the flag is absent", () => {
    delete process.env.DEMO_PORTAL_ENABLED;
    expect(() => DemoLayout({ children: <p>Hidden</p> })).toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it("returns not found when the flag is false", () => {
    process.env.DEMO_PORTAL_ENABLED = "false";
    expect(() => DemoLayout({ children: <p>Hidden</p> })).toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it.each([
    ["/demo", "Welcome, Demo Customer", <DemoDashboardPage key="dashboard" />],
    ["/demo/bookings", "DEMO-BOOKING-001", <DemoBookingsPage key="bookings" />],
    ["/demo/offers", "DEMO-OFFER-001", <DemoOffersPage key="offers" />],
    [
      "/demo/account",
      "Demonstration customer",
      <DemoAccountPage key="account" />,
    ],
  ])("renders %s without a session or API", (path, expected, page) => {
    renderEnabledRoute(path, page);
    expect(screen.getByText(expected)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Demonstration Preview — synthetic data only. No booking or transaction is created.",
      ),
    ).toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(apiClientImported).not.toHaveBeenCalled();
    expect(sessionBootstrapImported).not.toHaveBeenCalled();
  });

  it("contains no offer action control and keeps demonstration-only explanation", () => {
    renderEnabledRoute("/demo/offers", <DemoOffersPage />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getAllByText(DEMO_OFFER_READ_ONLY_LABEL)).toHaveLength(2);
    expect(screen.getAllByText(DEMO_OFFER_INERT_LABEL)).toHaveLength(2);
  });

  it("does not present transactional action labels", () => {
    renderEnabledRoute("/demo", <DemoDashboardPage />);
    const page = document.body.textContent ?? "";
    for (const label of [
      "Request a flight",
      "Create request",
      "Book now",
      "Pay",
      "Confirm booking",
      "Select offer",
      "Accept offer",
      "Reserve",
      "Save profile",
    ]) {
      expect(page.toLowerCase()).not.toContain(label.toLowerCase());
    }
  });
});

describe("demo search-indexing hardening", () => {
  it("marks the whole /demo tree noindex, nofollow (incl. Googlebot)", () => {
    const robots = demoMetadata.robots;
    expect(robots).not.toBeNull();
    expect(typeof robots).toBe("object");
    const directive = robots as {
      index?: boolean;
      follow?: boolean;
      googleBot?: { index?: boolean; follow?: boolean };
    };
    expect(directive.index).toBe(false);
    expect(directive.follow).toBe(false);
    expect(directive.googleBot?.index).toBe(false);
    expect(directive.googleBot?.follow).toBe(false);
  });

  it("overrides inherited marketing metadata for the /demo tree", () => {
    expect(demoMetadata.title).toBe(DEMO_METADATA_TITLE);
    expect(demoMetadata.description).toBe(DEMO_METADATA_DESCRIPTION);
    expect(JSON.stringify(demoMetadata)).not.toContain(
      "Premium Private Aviation Marketplace",
    );
    const robots = demoMetadata.robots as {
      index?: boolean;
      follow?: boolean;
      googleBot?: { index?: boolean; follow?: boolean };
    };
    expect(robots.index).toBe(false);
    expect(robots.follow).toBe(false);
    expect(robots.googleBot?.index).toBe(false);
    expect(robots.googleBot?.follow).toBe(false);
  });

  it("does not apply demo robots directives to the root (/, /login, /portal) layout", () => {
    // The robots directive lives only on the /demo layout subtree; the root layout that
    // wraps `/`, `/login`, and `/portal` must not carry a noindex directive.
    expect(rootMetadata.robots ?? null).toBeNull();
  });
});
