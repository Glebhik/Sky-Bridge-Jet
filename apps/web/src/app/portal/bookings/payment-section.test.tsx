import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BookingPaymentSection } from "@/app/portal/bookings/payment-section";
import type { CustomerBooking, CustomerPayment } from "@/lib/api/types";

const booking: CustomerBooking = {
  id: "booking",
  reference: "SBJ-1",
  trip_request_id: "trip",
  operator_offer_id: "offer",
  status: "PENDING_OPERATOR_CONFIRMATION",
  currency: "EUR",
  total_amount_minor: 10000,
  tax_amount_minor: 0,
  operator_legal_name: "Operator",
  aircraft_registration: "EI-ONE",
  aircraft_manufacturer: "Cessna",
  aircraft_model: "CJ3+",
  aircraft_category: "LIGHT_JET",
  confirmed_at: null,
  cancelled_at: null,
  cancellation_actor: null,
  cancellation_reason: null,
  created_at: "2026-08-26T10:00:00Z",
  updated_at: "2026-08-26T10:00:00Z",
};

function payment(
  status: string,
  extra: Partial<CustomerPayment> = {},
): CustomerPayment {
  return {
    id: "payment",
    booking_id: booking.id,
    status,
    currency: "EUR",
    total_amount_minor: 10000,
    authorized_amount_minor: status === "AUTHORIZED" ? 10000 : null,
    captured_amount_minor: status === "CAPTURED" ? 10000 : 0,
    refunded_amount_minor:
      status === "REFUNDED"
        ? 10000
        : status === "PARTIALLY_REFUNDED"
          ? 5000
          : 0,
    requires_customer_action: false,
    authorized_at: null,
    captured_at: null,
    cancelled_at: null,
    created_at: "2026-08-26T10:00:00Z",
    updated_at: "2026-08-26T10:00:00Z",
    ...extra,
  };
}

function show(value: CustomerPayment) {
  render(
    <BookingPaymentSection
      booking={booking}
      discovery="ready"
      payment={value}
      pending={false}
      message={undefined}
      onAuthorize={vi.fn()}
      onRetrySame={vi.fn()}
      onRefresh={vi.fn()}
    />,
  );
}

describe("Booking Payment factual status presentation", () => {
  it.each([
    [
      "AUTHORIZED",
      "Payment authorized",
      "Payment has not been captured by this step.",
    ],
    [
      "AUTHORIZATION_FAILED",
      "Payment authorization was not completed",
      "Try authorization again",
    ],
    ["CAPTURED", "Payment captured", "Captured amount: €100.00 EUR."],
    ["CANCELLED", "Payment cancelled", "This Payment is no longer active."],
    [
      "PARTIALLY_REFUNDED",
      "Payment partially refunded",
      "Refunded amount: €50.00 EUR.",
    ],
    ["REFUNDED", "Payment refunded", "Refunded amount: €100.00 EUR."],
    [
      "FUTURE_STATE",
      "Payment status unavailable",
      "No Payment action is available",
    ],
  ])(
    "renders %s without inventing a financial outcome",
    (status, title, detail) => {
      show(payment(status));
      expect(screen.getByText(title)).toBeTruthy();
      expect(screen.getByText(new RegExp(detail))).toBeTruthy();
      expect(
        screen.queryByText(/Paid|Charged|Settled|Ticketed|Payment complete/),
      ).toBeNull();
    },
  );

  it("prioritizes factual additional-verification state without fake controls", () => {
    show(payment("CREATED", { requires_customer_action: true }));
    expect(screen.getByText("Additional verification required")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /verify/i })).toBeNull();
  });
});
