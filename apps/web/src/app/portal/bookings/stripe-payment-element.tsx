"use client";

import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useRef, useState } from "react";

import { Alert, Button } from "@/components/ui/primitives";

const publishableKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
const stripePromise =
  publishableKey?.startsWith("pk_test_") === true
    ? loadStripe(publishableKey)
    : null;

function StripeConfirmation({
  onComplete,
}: {
  readonly onComplete: () => Promise<void>;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  const confirm = async () => {
    if (!stripe || !elements || submitting) return;
    setSubmitting(true);
    setError(null);
    const result = await stripe.confirmPayment({
      elements,
      redirect: "if_required",
      confirmParams: { return_url: window.location.href },
    });
    if (result.error) {
      setError(
        result.error.message ?? "Additional verification was not completed.",
      );
      setSubmitting(false);
      requestAnimationFrame(() => errorRef.current?.focus());
      return;
    }
    await onComplete();
    setSubmitting(false);
  };

  return (
    <div className="booking-payment__stripe">
      <p>
        Enter payment details in Stripe’s secure hosted fields. Sky Bridge Jet
        never receives or stores card numbers, security codes, or expiry dates.
      </p>
      <PaymentElement />
      {error ? (
        <div ref={errorRef} tabIndex={-1}>
          <Alert tone="error" title="Verification not completed">
            {error}
          </Alert>
        </div>
      ) : null}
      <Button
        type="button"
        disabled={!stripe || !elements || submitting}
        onClick={() => void confirm()}
      >
        {submitting ? "Confirming authorization…" : "Confirm authorization"}
      </Button>
      <p role="status" aria-live="polite">
        {submitting
          ? "Authorization processing. Do not close this page."
          : "This requests authorization only; it does not capture payment."}
      </p>
    </div>
  );
}

export function StripePaymentElement({
  clientSecret,
  onComplete,
}: {
  readonly clientSecret: string;
  readonly onComplete: () => Promise<void>;
}) {
  if (!stripePromise) {
    return (
      <Alert tone="error" title="Secure payment form unavailable">
        Stripe test-mode configuration is unavailable. No payment details can be
        entered.
      </Alert>
    );
  }
  return (
    <Elements stripe={stripePromise} options={{ clientSecret }}>
      <StripeConfirmation onComplete={onComplete} />
    </Elements>
  );
}
