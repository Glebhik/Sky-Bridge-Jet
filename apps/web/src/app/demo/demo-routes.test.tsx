import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DemoAccountPage from "@/app/demo/account/page";
import DemoBookingsPage from "@/app/demo/bookings/page";
import DemoLayout from "@/app/demo/layout";
import DemoDashboardPage from "@/app/demo/page";
import DemoOffersPage from "@/app/demo/offers/page";

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

  it("keeps every offer action visibly disabled and demo-only", () => {
    renderEnabledRoute("/demo/offers", <DemoOffersPage />);
    const actions = screen.getAllByRole("button", {
      name: "Demo only — selection unavailable",
    });
    expect(actions).toHaveLength(2);
    for (const action of actions) expect(action).toBeDisabled();
  });
});
