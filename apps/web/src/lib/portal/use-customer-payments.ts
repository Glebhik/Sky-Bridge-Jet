"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  CustomerPayment,
  CustomerPaymentClientAction,
} from "@/lib/api/types";

export type PaymentActionMessage =
  | { readonly kind: "unknown"; readonly text: string }
  | { readonly kind: "error"; readonly text: string }
  | { readonly kind: "conflict"; readonly text: string };

export type CustomerPaymentState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | {
      readonly status: "ready";
      readonly byBooking: Readonly<Record<string, CustomerPayment>>;
      readonly refreshing: boolean;
    };

function indexPayments(
  payments: readonly CustomerPayment[],
): Readonly<Record<string, CustomerPayment>> {
  return Object.fromEntries(
    payments.map((payment) => [payment.booking_id, payment]),
  );
}

/**
 * One authoritative Payment collection read for the displayed Booking set plus the one
 * customer B0 mutation. Request generations and aborts prevent an older GET from replacing
 * a newer POST result. Idempotency keys exist only in memory and survive an unknown transport
 * result for same-attempt retry; organization identity changes invalidate everything.
 */
export function useCustomerPayments(
  bookingIds: readonly string[],
  organizationId: string | null,
  enabled: boolean,
): {
  readonly state: CustomerPaymentState;
  readonly pendingBookingId: string | null;
  readonly messages: Readonly<Record<string, PaymentActionMessage>>;
  readonly clientActions: Readonly<Record<string, CustomerPaymentClientAction>>;
  readonly refresh: () => Promise<void>;
  readonly authorize: (
    bookingId: string,
    retrySameAttempt?: boolean,
  ) => Promise<void>;
  readonly completeClientAction: (bookingId: string) => Promise<void>;
} {
  const identity = `${organizationId ?? "none"}:${bookingIds.join(",")}`;
  const [state, setState] = useState<CustomerPaymentState>({
    status: "loading",
  });
  const [pendingBookingId, setPendingBookingId] = useState<string | null>(null);
  const [messages, setMessages] = useState<
    Readonly<Record<string, PaymentActionMessage>>
  >({});
  const [clientActions, setClientActions] = useState<
    Readonly<Record<string, CustomerPaymentClientAction>>
  >({});
  const identityRef = useRef(identity);
  const generationRef = useRef(0);
  const readControllerRef = useRef<AbortController | null>(null);
  const pendingRef = useRef<Set<string>>(new Set());
  const attemptsRef = useRef<Map<string, string>>(new Map());
  const refreshRef = useRef<() => Promise<void>>(async () => undefined);

  useEffect(() => {
    identityRef.current = identity;
    generationRef.current += 1;
    readControllerRef.current?.abort();
    readControllerRef.current = null;
    pendingRef.current.clear();
    attemptsRef.current.clear();
    setPendingBookingId(null);
    setMessages({});
    setClientActions({});

    if (!enabled || organizationId === null || bookingIds.length === 0) {
      setState({ status: "loading" });
      refreshRef.current = async () => undefined;
      return;
    }

    let disposed = false;
    const currentIdentity = identity;

    const read = async () => {
      const generation = ++generationRef.current;
      readControllerRef.current?.abort();
      const controller = new AbortController();
      readControllerRef.current = controller;
      setState((current) =>
        current.status === "ready"
          ? { ...current, refreshing: true }
          : { status: "loading" },
      );
      try {
        const payments = await portalApi.listPayments(
          bookingIds,
          organizationId,
          controller.signal,
        );
        if (
          disposed ||
          controller.signal.aborted ||
          identityRef.current !== currentIdentity ||
          generationRef.current !== generation
        )
          return;
        const resolvedBookingIds = new Set(
          payments
            .filter((payment) => !payment.requires_customer_action)
            .map((payment) => payment.booking_id),
        );
        for (const bookingId of resolvedBookingIds)
          attemptsRef.current.delete(bookingId);
        if (resolvedBookingIds.size > 0) {
          setMessages((current) =>
            Object.fromEntries(
              Object.entries(current).filter(
                ([bookingId]) => !resolvedBookingIds.has(bookingId),
              ),
            ),
          );
        }
        setState({
          status: "ready",
          byBooking: indexPayments(payments),
          refreshing: false,
        });
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setState({
          status: "error",
          message:
            error instanceof ApiError && error.isForbidden
              ? "You do not have access to Payment status for these Bookings."
              : "Payment status could not be confirmed. Refresh to try again.",
        });
      } finally {
        if (readControllerRef.current === controller)
          readControllerRef.current = null;
      }
    };

    refreshRef.current = read;
    void read();
    return () => {
      disposed = true;
      generationRef.current += 1;
      controllerCleanup(readControllerRef);
      refreshRef.current = async () => undefined;
    };
  }, [bookingIds, enabled, identity, organizationId]);

  const refresh = useCallback(() => refreshRef.current(), []);

  const authorize = useCallback(
    async (bookingId: string, retrySameAttempt = false) => {
      if (organizationId === null || identityRef.current !== identity) return;
      if (pendingRef.current.has(bookingId)) return;
      const unresolvedKey = attemptsRef.current.get(bookingId);
      if (
        (retrySameAttempt && unresolvedKey === undefined) ||
        (!retrySameAttempt && unresolvedKey !== undefined)
      )
        return;
      pendingRef.current.add(bookingId);
      setPendingBookingId(bookingId);
      setMessages((current) => {
        const next = { ...current };
        delete next[bookingId];
        return next;
      });

      readControllerRef.current?.abort();
      readControllerRef.current = null;
      const generation = ++generationRef.current;
      const key = retrySameAttempt ? unresolvedKey : crypto.randomUUID();
      if (key === undefined) return;
      attemptsRef.current.set(bookingId, key);
      try {
        const payment = await portalApi.initiatePayment(
          bookingId,
          { idempotency_key: key },
          organizationId,
        );
        if (
          identityRef.current !== identity ||
          generationRef.current !== generation
        )
          return;
        setState((current) => ({
          status: "ready",
          byBooking: {
            ...(current.status === "ready" ? current.byBooking : {}),
            [payment.booking_id]: payment,
          },
          refreshing: false,
        }));
        attemptsRef.current.delete(bookingId);
        if (payment.client_action) {
          setClientActions((current) => ({
            ...current,
            [bookingId]: payment.client_action!,
          }));
        }
      } catch (error) {
        if (
          identityRef.current !== identity ||
          generationRef.current !== generation
        )
          return;
        if (error instanceof ApiError && error.status === 409) {
          attemptsRef.current.delete(bookingId);
          await refreshRef.current();
          if (identityRef.current === identity) {
            setMessages((current) => ({
              ...current,
              [bookingId]: {
                kind: "conflict",
                text: "Payment status was refreshed after the request conflicted with current state.",
              },
            }));
          }
        } else if (error instanceof ApiError && error.kind === "network") {
          setMessages((current) => ({
            ...current,
            [bookingId]: {
              kind: "unknown",
              text: "We could not confirm the authorization result.",
            },
          }));
        } else {
          attemptsRef.current.delete(bookingId);
          setMessages((current) => ({
            ...current,
            [bookingId]: {
              kind: "error",
              text:
                error instanceof ApiError && error.isForbidden
                  ? "You do not have permission to authorize this Payment."
                  : error instanceof ApiError && error.status === 404
                    ? "This Booking is no longer available for Payment authorization."
                    : "Payment authorization could not be completed.",
            },
          }));
        }
      } finally {
        pendingRef.current.delete(bookingId);
        setPendingBookingId((current) =>
          current === bookingId ? null : current,
        );
      }
    },
    [identity, organizationId],
  );

  const completeClientAction = useCallback(async (bookingId: string) => {
    setClientActions((current) => {
      const next = { ...current };
      delete next[bookingId];
      return next;
    });
    await refreshRef.current();
  }, []);

  return useMemo(
    () => ({
      state,
      pendingBookingId,
      messages,
      clientActions,
      refresh,
      authorize,
      completeClientAction,
    }),
    [
      authorize,
      clientActions,
      completeClientAction,
      messages,
      pendingBookingId,
      refresh,
      state,
    ],
  );
}

function controllerCleanup(ref: { current: AbortController | null }): void {
  ref.current?.abort();
  ref.current = null;
}
