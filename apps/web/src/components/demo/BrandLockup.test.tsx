import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { BrandLockup } from "@/components/demo/BrandLockup";
import { DEMO_BRAND_NAME, DEMO_BRAND_SUBLINE } from "@/lib/demo/copy";

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

describe("BrandLockup", () => {
  it("renders the text lockup without substituting an emblem", () => {
    const { container } = render(<BrandLockup />);
    expect(
      screen.getByRole("link", { name: new RegExp(DEMO_BRAND_NAME, "i") }),
    ).toHaveAttribute("href", "/demo");
    expect(screen.getByText(DEMO_BRAND_SUBLINE)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});
