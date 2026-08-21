export const DEMO_NAV_ITEMS = [
  { href: "/demo", label: "Dashboard" },
  { href: "/demo/bookings", label: "Bookings" },
  { href: "/demo/offers", label: "Offers" },
  { href: "/demo/account", label: "Account" },
] as const;

export function isDemoNavActive(pathname: string, href: string): boolean {
  return href === "/demo"
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}
