"use client";

import { useState } from "react";

import { Alert, Button } from "@/components/ui/primitives";
import type { CustomerBooking, CustomerPayment } from "@/lib/api/types";
import type { CustomerPaymentClientAction } from "@/lib/api/types";
import { StripePaymentElement } from "@/app/portal/bookings/stripe-payment-element";
import { formatOfferMoney } from "@/lib/portal/offers";
import type {
  CustomerPaymentState,
  PaymentActionMessage,
} from "@/lib/portal/use-customer-payments";

function paymentPresentation(payment: CustomerPayment): {
  readonly title: string;
  readonly detail: string;
  readonly tone: "info" | "error" | "warning" | "success";
} {
  if (payment.requires_customer_action)
    return {
      title: "Additional verification required",
      detail:
        "Payment authorization needs additional verification. Use the secure Stripe form when it is available below.",
      tone: "warning",
    };
  switch (payment.status) {
    case "AUTHORIZED":
      return {
        title: "Payment authorized",
        detail: "Payment has not been captured by this step.",
        tone: "success",
      };
    case "AUTHORIZATION_FAILED":
      return {
        title: "Payment authorization was not completed",
        detail: "You may start a new authorization attempt.",
        tone: "error",
      };
    case "CREATED":
      return {
        title: "Payment authorization not completed",
        detail: "You may continue with an authorization attempt.",
        tone: "info",
      };
    case "CAPTURED":
      return {
        title: "Payment captured",
        detail: `Captured amount: ${formatOfferMoney(payment.captured_amount_minor, payment.currency)} ${payment.currency}.`,
        tone: "success",
      };
    case "CANCELLED":
      return {
        title: "Payment cancelled",
        detail: "This Payment is no longer active.",
        tone: "info",
      };
    case "PARTIALLY_REFUNDED":
      return {
        title: "Payment partially refunded",
        detail: `Refunded amount: ${formatOfferMoney(payment.refunded_amount_minor, payment.currency)} ${payment.currency}.`,
        tone: "info",
      };
    case "REFUNDED":
      return {
        title: "Payment refunded",
        detail: `Refunded amount: ${formatOfferMoney(payment.refunded_amount_minor, payment.currency)} ${payment.currency}.`,
        tone: "info",
      };
    default:
      return {
        title: "Payment status unavailable",
        detail: "No Payment action is available for this status.",
        tone: "warning",
      };
  }
}

export function BookingPaymentSection({
  booking,
  discovery,
  payment,
  pending,
  message,
  onAuthorize,
  onRetrySame,
  onRefresh,
  clientAction,
  onClientActionComplete = async () => undefined,
}: {
  readonly booking: CustomerBooking;
  readonly discovery: CustomerPaymentState["status"];
  readonly payment: CustomerPayment | undefined;
  readonly pending: boolean;
  readonly message: PaymentActionMessage | undefined;
  readonly onAuthorize: () => Promise<void>;
  readonly onRetrySame: () => Promise<void>;
  readonly onRefresh: () => Promise<void>;
  readonly clientAction?: CustomerPaymentClientAction;
  readonly onClientActionComplete?: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const bookingEligible =
    booking.status === "PENDING_OPERATOR_CONFIRMATION" ||
    booking.status === "CONFIRMED";
  const paymentEligible =
    payment === undefined ||
    payment.status === "CREATED" ||
    payment.status === "AUTHORIZATION_FAILED";
  const canAuthorize =
    discovery === "ready" &&
    bookingEligible &&
    paymentEligible &&
    !payment?.requires_customer_action &&
    message?.kind !== "unknown";
  const presentation = payment ? paymentPresentation(payment) : null;

  const submit = async () => {
    setConfirming(false);
    await onAuthorize();
  };

  return (
    <section
      className="booking-payment"
      aria-labelledby={`payment-${booking.id}`}
      aria-busy={pending}
    >
      <h3 id={`payment-${booking.id}`}>Payment</h3>
      {discovery === "loading" ? (
        <p role="status">Confirming Payment status…</p>
      ) : discovery === "error" ? (
        <Alert tone="error" title="Payment status unavailable">
          Payment status could not be confirmed. Authorization is unavailable
          until a successful refresh.
        </Alert>
      ) : presentation ? (
        <Alert tone={presentation.tone} title={presentation.title}>
          {presentation.detail}
        </Alert>
      ) : (
        <p>No Payment authorization has been recorded for this Booking.</p>
      )}

      {message ? (
        <Alert
          tone={message.kind === "unknown" ? "warning" : "error"}
          title={
            message.kind === "unknown" ? "Result not confirmed" : undefined
          }
        >
          {message.text}
        </Alert>
      ) : null}

      {clientAction ? (
        <StripePaymentElement
          clientSecret={clientAction.client_secret}
          onComplete={onClientActionComplete}
        />
      ) : null}

      {confirming ? (
        <div
          className="booking-payment__confirmation"
          role="group"
          aria-labelledby={`payment-confirm-${booking.id}`}
        >
          <h4 id={`payment-confirm-${booking.id}`}>Authorize this Payment?</h4>
          <p>
            Sky Bridge Jet will request authorization for the Booking amount of{" "}
            <strong>
              {formatOfferMoney(booking.total_amount_minor, booking.currency)}{" "}
              {booking.currency}
            </strong>
            . This step does not capture payment. Operator confirmation remains
            a separate Booking state.
          </p>
          <div className="booking-payment__actions">
            <Button
              type="button"
              variant="ghost"
              disabled={pending}
              onClick={() => setConfirming(false)}
            >
              Keep reviewing
            </Button>
            <Button
              type="button"
              disabled={pending}
              onClick={() => void submit()}
            >
              {pending ? "Authorizing…" : "Authorize payment"}
            </Button>
          </div>
        </div>
      ) : canAuthorize ? (
        <Button
          type="button"
          disabled={pending}
          onClick={() => setConfirming(true)}
        >
          {payment?.status === "AUTHORIZATION_FAILED"
            ? "Try authorization again"
            : "Authorize payment"}
        </Button>
      ) : null}

      {message?.kind === "unknown" ? (
        <div className="booking-payment__actions">
          <Button
            type="button"
            variant="secondary"
            disabled={pending}
            onClick={() => void onRefresh()}
          >
            Refresh Payment status
          </Button>
          <Button
            type="button"
            disabled={pending}
            onClick={() => void onRetrySame()}
          >
            Retry same authorization attempt
          </Button>
        </div>
      ) : null}
    </section>
  );
}
