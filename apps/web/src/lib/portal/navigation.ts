/**
 * The Customer Portal shell navigation. Scope is the Phase 9.1 shell only: a dashboard
 * home plus honest placeholders for the surfaces the accepted design names (bookings,
 * offers, account). The feature workflows behind them are later phases.
 */
export interface PortalNavItem {
  readonly href: string;
  readonly label: string;
}

export const PORTAL_NAV_ITEMS: readonly PortalNavItem[] = [
  { href: "/portal", label: "Dashboard" },
  { href: "/portal/bookings", label: "Bookings" },
  { href: "/portal/offers", label: "Offers" },
  { href: "/portal/account", label: "Account" },
];

/** Active when the path matches exactly, or (for non-root items) is nested beneath it. */
export function isActiveNavItem(currentPath: string, href: string): boolean {
  if (href === "/portal") return currentPath === "/portal";
  return currentPath === href || currentPath.startsWith(`${href}/`);
}
