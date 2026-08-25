/**
 * The Customer Portal navigation: a dashboard home, the Phase 9.3.A read-only trip-requests
 * surface, and honest placeholders for the remaining accepted-design surfaces (bookings,
 * offers, account). The create/manage workflows behind trip requests, and the offer/booking
 * feature workflows, are later phases.
 */
export interface PortalNavItem {
  readonly href: string;
  readonly label: string;
}

export const PORTAL_NAV_ITEMS: readonly PortalNavItem[] = [
  { href: "/portal", label: "Dashboard" },
  { href: "/portal/trip-requests", label: "Trip requests" },
  { href: "/portal/bookings", label: "Bookings" },
  { href: "/portal/offers", label: "Offers" },
  { href: "/portal/account", label: "Account" },
];

/** Active when the path matches exactly, or (for non-root items) is nested beneath it. */
export function isActiveNavItem(currentPath: string, href: string): boolean {
  if (href === "/portal") return currentPath === "/portal";
  return currentPath === href || currentPath.startsWith(`${href}/`);
}
