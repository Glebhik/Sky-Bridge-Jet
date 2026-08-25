import type { CustomerOffer } from "@/lib/api/types";

export function formatOfferMoney(
  amountMinor: number,
  currency: string,
): string {
  return new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

export function compareCustomerOffers(
  a: CustomerOffer,
  b: CustomerOffer,
): number {
  const currency = a.currency.localeCompare(b.currency);
  if (currency !== 0) return currency;
  if (a.total_amount_minor !== b.total_amount_minor)
    return a.total_amount_minor - b.total_amount_minor;
  const validity = (b.valid_until ?? "").localeCompare(a.valid_until ?? "");
  if (validity !== 0) return validity;
  const created = a.created_at.localeCompare(b.created_at);
  return created !== 0 ? created : a.id.localeCompare(b.id);
}

export type OfferAvailability =
  | "available"
  | "expired"
  | "selected"
  | "unavailable";

export function offerAvailability(status: string): OfferAvailability {
  if (status === "SUBMITTED") return "available";
  if (status === "EXPIRED") return "expired";
  if (status === "SELECTED") return "selected";
  return "unavailable";
}

export function serviceItems(value: string | null): readonly string[] {
  return (
    value
      ?.split(/[;,\n]/)
      .map((item) => item.trim())
      .filter(Boolean) ?? []
  );
}
