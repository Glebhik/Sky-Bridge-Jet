import type { CustomerBooking, CustomerOffer } from "@/lib/api/types";

export function canCreateBookingRequest(
  tripStatus: string,
  offer: CustomerOffer,
  now = Date.now(),
): boolean {
  if (tripStatus !== "SUBMITTED" || offer.status !== "SELECTED") return false;
  if (offer.valid_until === null) return false;
  const validUntil = Date.parse(offer.valid_until);
  return Number.isFinite(validUntil) && validUntil > now;
}

export function bookingStatusLabel(status: string): string {
  if (status === "PENDING_OPERATOR_CONFIRMATION")
    return "Awaiting operator confirmation";
  if (status === "CONFIRMED") return "Confirmed by the operator";
  if (status === "REJECTED")
    return "The operator could not confirm this booking";
  if (status === "CANCELLED") return "This booking was cancelled";
  return "Booking status unavailable";
}

export function bookingStatusTone(
  status: CustomerBooking["status"] | string,
): "info" | "success" | "danger" | "neutral" {
  if (status === "PENDING_OPERATOR_CONFIRMATION") return "info";
  if (status === "CONFIRMED") return "success";
  if (status === "REJECTED") return "danger";
  return "neutral";
}
