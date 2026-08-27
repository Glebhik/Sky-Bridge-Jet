import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const confirmPayment = vi.fn();
const loadStripe = vi.fn(() => Promise.resolve({}));

vi.mock("@stripe/stripe-js", () => ({ loadStripe }));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PaymentElement: () => <div data-testid="stripe-hosted-payment-element" />,
  useElements: () => ({ mounted: true }),
  useStripe: () => ({ confirmPayment }),
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
  vi.clearAllMocks();
});

describe("StripePaymentElement", () => {
  it("fails closed without a test-mode publishable key and renders no raw card fields", async () => {
    const { StripePaymentElement } =
      await import("@/app/portal/bookings/stripe-payment-element");
    render(
      <StripePaymentElement
        clientSecret="pi_secret_ephemeral"
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByText("Secure payment form unavailable")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByTestId("stripe-hosted-payment-element")).toBeNull();
    expect(loadStripe).not.toHaveBeenCalled();
  });

  it("rejects a live-mode publishable key before Stripe.js initialization", async () => {
    vi.stubEnv("NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY", "pk_live_forbidden");
    const { StripePaymentElement } =
      await import("@/app/portal/bookings/stripe-payment-element");
    render(
      <StripePaymentElement
        clientSecret="pi_secret_must_not_mount"
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByText("Secure payment form unavailable")).toBeTruthy();
    expect(loadStripe).not.toHaveBeenCalled();
    expect(screen.queryByTestId("stripe-hosted-payment-element")).toBeNull();
  });

  it("uses hosted fields and explicitly confirms authorization in test mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY", "pk_test_local_only");
    confirmPayment.mockResolvedValue({});
    const onComplete = vi.fn().mockResolvedValue(undefined);
    const { StripePaymentElement } =
      await import("@/app/portal/bookings/stripe-payment-element");
    render(
      <StripePaymentElement
        clientSecret="pi_secret_ephemeral"
        onComplete={onComplete}
      />,
    );

    expect(loadStripe).toHaveBeenCalledWith("pk_test_local_only");
    expect(screen.getByTestId("stripe-hosted-payment-element")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm authorization" }),
    );
    await waitFor(() => expect(confirmPayment).toHaveBeenCalledTimes(1));
    expect(confirmPayment).toHaveBeenCalledWith(
      expect.objectContaining({ redirect: "if_required" }),
    );
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });
});
