"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Alert, Button, LoadingState } from "@/components/ui/primitives";
import { portalApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CustomerBooking, CustomerOffer } from "@/lib/api/types";
import {
  bookingStatusLabel,
  canCreateBookingRequest,
} from "@/lib/portal/bookings";

interface Props {
  readonly tripRequestId: string;
  readonly tripStatus: string;
  readonly selectedOffer: CustomerOffer;
  readonly organizationId?: string;
}

type ReadState =
  | { readonly status: "loading" }
  | { readonly status: "none" }
  | { readonly status: "found"; readonly booking: CustomerBooking }
  | { readonly status: "error" };

function EligibleBookingCreatePanel({
  tripRequestId,
  tripStatus,
  selectedOffer,
  organizationId,
}: Props) {
  const pendingRef = useRef(false);
  const [readState, setReadState] = useState<ReadState>({ status: "loading" });
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [createError, setCreateError] = useState<
    "forbidden" | "missing" | "conflict" | "other" | null
  >(null);

  const readAuthoritativeBooking = async (
    signal?: AbortSignal,
  ): Promise<CustomerBooking | null> => {
    try {
      return await portalApi.getTripRequestBooking(
        tripRequestId,
        organizationId,
        signal,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void portalApi
      .getTripRequestBooking(tripRequestId, organizationId, controller.signal)
      .then((booking) =>
        setReadState(
          booking ? { status: "found", booking } : { status: "none" },
        ),
      )
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        if (error instanceof ApiError && error.status === 404) {
          setReadState({ status: "none" });
          return;
        }
        setReadState({ status: "error" });
      });
    return () => controller.abort();
  }, [tripRequestId, organizationId]);

  const createBooking = async () => {
    if (pendingRef.current) return;
    if (!canCreateBookingRequest(tripStatus, selectedOffer)) return;
    pendingRef.current = true;
    setPending(true);
    setCreateError(null);
    try {
      const booking = await portalApi.createBooking(
        {
          trip_request_id: tripRequestId,
          operator_offer_id: selectedOffer.id,
        },
        organizationId,
      );
      setReadState({ status: "found", booking });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          const booking = await readAuthoritativeBooking();
          if (booking) {
            setReadState({ status: "found", booking });
          } else {
            setCreateError("conflict");
          }
        } catch {
          setCreateError("conflict");
        }
      } else if (error instanceof ApiError && error.status === 403) {
        setCreateError("forbidden");
      } else if (error instanceof ApiError && error.status === 404) {
        setCreateError("missing");
      } else {
        setCreateError("other");
      }
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  if (readState.status === "loading")
    return <LoadingState label="Checking booking status…" />;
  if (readState.status === "found")
    return (
      <Alert tone="info" title="Booking request created">
        <p>
          {readState.booking.reference}:{" "}
          {bookingStatusLabel(readState.booking.status)}.
        </p>
        <Link className="card__link" href="/portal/bookings">
          View bookings
        </Link>
      </Alert>
    );
  if (readState.status === "error")
    return (
      <Alert tone="error" title="Booking status couldn’t be checked">
        Refresh this page before creating a booking request.
      </Alert>
    );

  return (
    <section
      className={
        pending
          ? "offer-confirmation booking-create-panel offer-confirmation--pending"
          : "offer-confirmation booking-create-panel"
      }
      aria-labelledby="booking-confirmation-title"
      aria-busy={pending}
    >
      {!confirming ? (
        <>
          <h3 id="booking-confirmation-title">Ready to request a booking?</h3>
          <p>The selected offer still requires confirmation by the operator.</p>
          <Button
            variant="primary"
            disabled={pending}
            onClick={() => setConfirming(true)}
          >
            Create booking request
          </Button>
        </>
      ) : (
        <>
          <h3 id="booking-confirmation-title">Create booking request</h3>
          <p>
            This creates a booking request for the selected offer. Operator
            confirmation is still required. No payment is taken and no charge
            occurs in this step.
          </p>
          <div className="offer-confirmation__actions">
            <Button
              variant="secondary"
              disabled={pending}
              onClick={() => setConfirming(false)}
            >
              Keep offer selected
            </Button>
            <Button
              variant="primary"
              disabled={pending}
              onClick={() => void createBooking()}
            >
              {pending ? "Creating…" : "Create booking request"}
            </Button>
          </div>
        </>
      )}
      {createError === "forbidden" ? (
        <Alert tone="error" title="Booking request not permitted">
          You don’t have access to create this booking request.
        </Alert>
      ) : createError === "missing" ? (
        <Alert tone="error" title="Selected offer unavailable">
          This trip or selected offer is no longer available.
        </Alert>
      ) : createError === "conflict" ? (
        <Alert tone="warning" title="Booking status changed">
          A booking request could not be created. Refresh to check the current
          booking status before trying again.
        </Alert>
      ) : createError === "other" ? (
        <Alert tone="error" title="Booking request couldn’t be created">
          Your selected offer is unchanged. Check your connection and try again.
        </Alert>
      ) : null}
    </section>
  );
}

export function BookingCreatePanel(props: Props) {
  if (!canCreateBookingRequest(props.tripStatus, props.selectedOffer))
    return null;
  return <EligibleBookingCreatePanel {...props} />;
}
