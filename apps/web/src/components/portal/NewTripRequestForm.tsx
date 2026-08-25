"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { useActiveOrganization } from "@/components/session/org-context";
import { portalApi } from "@/lib/api/client";
import type { Airport } from "@/lib/api/types";
import { useApiResource } from "@/lib/api/use-resource";
import {
  Alert,
  Button,
  Card,
  Field,
  LoadingState,
  PageHeading,
} from "@/components/ui/primitives";
import { AirportPicker } from "@/components/portal/AirportPicker";
import {
  buildProgress,
  emptyForm,
  emptyPassenger,
  messageForPassengerError,
  messageForSubmitError,
  messageForTripCreateError,
  normalizeDeparture,
  runCreation,
  validateForm,
  type CreationPhase,
  type CreationProgress,
  type FieldErrors,
  type PassengerDraft,
  type TripRequestForm,
} from "@/lib/portal/trip-create";

/**
 * The Phase 9.3.B create-a-trip-request journey (client component). It drives an explicit
 * creation state machine over the real backend contracts: create real passengers inline,
 * create exactly one DRAFT trip request (never sending `customer_id`), then submit that same
 * DRAFT to SUBMITTED and navigate to its detail. Partial failures are recoverable without
 * duplicating passengers or the DRAFT, and every backend error is mapped to a safe message.
 */

const BUSY_PHASES: ReadonlySet<CreationPhase> = new Set([
  "creating_passengers",
  "creating_trip",
  "submitting_trip",
]);

function ctaLabel(phase: CreationPhase): string {
  switch (phase) {
    case "creating_passengers":
      return "Saving passengers…";
    case "creating_trip":
      return "Creating request…";
    case "submitting_trip":
      return "Submitting…";
    case "submit_error":
      return "Retry submission";
    case "passenger_error":
    case "trip_create_error":
      return "Try again";
    default:
      return "Create & submit request";
  }
}

export function NewTripRequestForm() {
  const router = useRouter();
  const { activeOrganizationId, hasCustomerContext } = useActiveOrganization();

  // Only fetch airports once there is a customer context (the picker is otherwise unreachable).
  const loadAirports = useCallback(
    (signal: AbortSignal): Promise<readonly Airport[]> =>
      hasCustomerContext ? portalApi.listAirports(signal) : Promise.resolve([]),
    [hasCustomerContext],
  );
  const airportsState = useApiResource<readonly Airport[]>(
    loadAirports,
    `airports:${hasCustomerContext ? "all" : "none"}`,
  );

  const [form, setForm] = useState<TripRequestForm>(emptyForm);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [phase, setPhase] = useState<CreationPhase>("editing");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const progressRef = useRef<CreationProgress | null>(null);
  // A synchronous in-flight guard: React state (`busy`) can lag two rapid clicks, so this ref
  // is the hard guarantee that one user action never starts two overlapping create/submit runs.
  const inFlightRef = useRef(false);
  // Render-time mirrors of the (ref-held) progress, so render never reads the ref directly.
  const [started, setStarted] = useState(false);
  const [createdIds, setCreatedIds] = useState<readonly (string | null)[]>([]);

  const busy = BUSY_PHASES.has(phase);

  /** Mirror the mutable progress into render state (called from handlers, never in render). */
  function syncFromProgress(progress: CreationProgress): void {
    setStarted(true);
    setCreatedIds(progress.passengers.map((slot) => slot.id));
  }

  function patch(update: Partial<TripRequestForm>): void {
    setForm((current) => ({ ...current, ...update }));
  }

  function patchPassenger(
    index: number,
    update: Partial<PassengerDraft>,
  ): void {
    setForm((current) => ({
      ...current,
      passengers: current.passengers.map((passenger, i) =>
        i === index ? { ...passenger, ...update } : passenger,
      ),
    }));
  }

  function addPassenger(): void {
    setForm((current) => ({
      ...current,
      passengers: [...current.passengers, emptyPassenger()],
    }));
  }

  function removePassenger(index: number): void {
    setForm((current) => ({
      ...current,
      passengers: current.passengers.filter((_, i) => i !== index),
    }));
  }

  /** True once a given passenger slot has a server id — its inputs are then locked. */
  function isCreated(index: number): boolean {
    return createdIds[index] != null;
  }

  const run = useCallback(async (progress: CreationProgress) => {
    setSubmitError(null);
    try {
      const submitted = await runCreation(portalApi, progress, setPhase);
      // Success: leave the CTA disabled and navigate to the real detail page.
      router.push(`/portal/trip-requests/${submitted.id}`);
    } catch (error) {
      // Derive the failing phase from progress: a created DRAFT means submit failed; all
      // passengers created (no DRAFT) means trip creation failed; otherwise passenger create.
      if (progress.draft !== null) {
        setPhase("submit_error");
        setSubmitError(messageForSubmitError(error));
      } else if (progress.passengers.every((slot) => slot.id !== null)) {
        setPhase("trip_create_error");
        setSubmitError(messageForTripCreateError());
      } else {
        setPhase("passenger_error");
        setSubmitError(messageForPassengerError());
      }
      syncFromProgress(progress);
    }
    // router is stable; portalApi is a module singleton.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handlePrimary(): Promise<void> {
    if (inFlightRef.current || busy) return; // hard + soft overlapping-submit guard
    inFlightRef.current = true;
    try {
      // Retry path: reuse the existing progress (created passengers + any DRAFT) verbatim, so a
      // retry NEVER recreates a passenger or the DRAFT. Corrections to not-yet-created
      // passengers are synced in by index; created slots and the DRAFT are untouched.
      const existing = progressRef.current;
      if (existing !== null) {
        existing.passengers.forEach((slot, index) => {
          const live = form.passengers[index];
          if (slot.id === null && live) slot.input = live;
        });
        await run(existing);
        return;
      }

      // Fresh start: validate, then build progress from the current form.
      const errors = validateForm(form);
      setFieldErrors(errors);
      if (Object.keys(errors).length > 0) {
        setPhase("editing");
        return;
      }
      const progress = buildProgress(form, activeOrganizationId ?? undefined);
      progressRef.current = progress;
      syncFromProgress(progress);
      await run(progress);
    } finally {
      inFlightRef.current = false;
    }
  }

  if (!hasCustomerContext) {
    return (
      <>
        <PageHeading title="New trip request" />
        <Alert tone="warning" title="No active customer account">
          You can create a trip request once your sign-in is linked to a
          customer account.
        </Alert>
      </>
    );
  }

  if (airportsState.status === "loading") {
    return (
      <>
        <PageHeading title="New trip request" />
        <LoadingState label="Loading airports…" />
      </>
    );
  }

  if (airportsState.status === "error") {
    return (
      <>
        <PageHeading title="New trip request" />
        <Alert tone="error" title="We couldn’t load airports">
          Please refresh to try again.
        </Alert>
      </>
    );
  }

  const airports = airportsState.data;
  const departureIso = normalizeDeparture(form.departure_at_local);

  return (
    <>
      <PageHeading
        title="New trip request"
        description="Tell us where you’re flying and who’s travelling. We’ll submit your request."
      />

      {phase === "passenger_error" || phase === "trip_create_error" ? (
        <Alert tone="error" title="We couldn’t complete your request">
          {submitError}
        </Alert>
      ) : null}
      {phase === "submit_error" ? (
        <Alert tone="warning" title="Not submitted yet">
          {submitError}
        </Alert>
      ) : null}

      <Card className="form-section">
        <h2 className="card__title">Journey</h2>
        <div className="journey-airports">
          <AirportPicker
            id="trip-origin"
            label="From"
            airports={airports}
            value={form.origin_airport_id}
            onChange={(id) => patch({ origin_airport_id: id })}
            error={fieldErrors.origin}
            disabled={busy || started}
          />
          <AirportPicker
            id="trip-destination"
            label="To"
            airports={airports}
            value={form.destination_airport_id}
            onChange={(id) => patch({ destination_airport_id: id })}
            error={fieldErrors.destination}
            disabled={busy || started}
          />
        </div>
        <Field
          id="trip-departure"
          label="Departure"
          type="datetime-local"
          value={form.departure_at_local}
          onChange={(event) =>
            patch({ departure_at_local: event.target.value })
          }
          disabled={busy || started}
        />
        {fieldErrors.departure ? (
          <p className="field__error" role="alert">
            {fieldErrors.departure}
          </p>
        ) : null}
      </Card>

      <Card className="form-section">
        <h2 className="card__title">Passengers</h2>
        {form.passengers.map((passenger, index) => (
          <fieldset className="passenger-fieldset" key={index}>
            <legend>
              Passenger {index + 1}
              {isCreated(index) ? " (saved)" : ""}
            </legend>
            <div className="passenger-name-row">
              <div>
                <Field
                  id={`passenger-${index}-first`}
                  label="First name"
                  value={passenger.first_name}
                  onChange={(event) =>
                    patchPassenger(index, { first_name: event.target.value })
                  }
                  disabled={busy || isCreated(index)}
                />
                {fieldErrors[`passenger.${index}.first_name`] ? (
                  <p className="field__error" role="alert">
                    {fieldErrors[`passenger.${index}.first_name`]}
                  </p>
                ) : null}
              </div>
              <div>
                <Field
                  id={`passenger-${index}-last`}
                  label="Last name"
                  value={passenger.last_name}
                  onChange={(event) =>
                    patchPassenger(index, { last_name: event.target.value })
                  }
                  disabled={busy || isCreated(index)}
                />
                {fieldErrors[`passenger.${index}.last_name`] ? (
                  <p className="field__error" role="alert">
                    {fieldErrors[`passenger.${index}.last_name`]}
                  </p>
                ) : null}
              </div>
            </div>
            <Field
              id={`passenger-${index}-dob`}
              label="Date of birth (optional)"
              type="date"
              value={passenger.date_of_birth}
              onChange={(event) =>
                patchPassenger(index, { date_of_birth: event.target.value })
              }
              disabled={busy || isCreated(index)}
            />
            {form.passengers.length > 1 && !started ? (
              <Button
                variant="ghost"
                type="button"
                onClick={() => removePassenger(index)}
                disabled={busy}
              >
                Remove passenger {index + 1}
              </Button>
            ) : null}
          </fieldset>
        ))}
        {!started ? (
          <Button
            variant="secondary"
            type="button"
            onClick={addPassenger}
            disabled={busy}
          >
            Add another passenger
          </Button>
        ) : null}
      </Card>

      <Card className="form-section">
        <h2 className="card__title">Requirements (optional)</h2>
        <Field
          id="trip-baggage"
          label="Baggage notes"
          value={form.requirements.baggage_notes}
          onChange={(event) =>
            patch({
              requirements: {
                ...form.requirements,
                baggage_notes: event.target.value,
              },
            })
          }
          disabled={busy || started}
        />
        <Field
          id="trip-catering"
          label="Catering notes"
          value={form.requirements.catering_notes}
          onChange={(event) =>
            patch({
              requirements: {
                ...form.requirements,
                catering_notes: event.target.value,
              },
            })
          }
          disabled={busy || started}
        />
        <Field
          id="trip-assistance"
          label="Special assistance"
          value={form.requirements.special_assistance_notes}
          onChange={(event) =>
            patch({
              requirements: {
                ...form.requirements,
                special_assistance_notes: event.target.value,
              },
            })
          }
          disabled={busy || started}
        />
        <Field
          id="trip-notes"
          label="Anything else"
          value={form.requirements.customer_notes}
          onChange={(event) =>
            patch({
              requirements: {
                ...form.requirements,
                customer_notes: event.target.value,
              },
            })
          }
          disabled={busy || started}
        />
        <label className="field__checkbox">
          <input
            type="checkbox"
            checked={form.requirements.ground_transport_requested}
            onChange={(event) =>
              patch({
                requirements: {
                  ...form.requirements,
                  ground_transport_requested: event.target.checked,
                },
              })
            }
            disabled={busy || started}
          />
          Ground transport requested
        </label>
      </Card>

      <Card className="form-section form-section--review">
        <h2 className="card__title">Review</h2>
        <dl className="detail-list">
          <div>
            <dt>Route</dt>
            <dd>
              {airportName(airports, form.origin_airport_id)} →{" "}
              {airportName(airports, form.destination_airport_id)}
            </dd>
          </div>
          <div>
            <dt>Departure</dt>
            <dd>
              {departureIso
                ? new Date(departureIso).toLocaleString()
                : "Not set"}
            </dd>
          </div>
          <div>
            <dt>Passengers</dt>
            <dd>{form.passengers.length}</dd>
          </div>
        </dl>
        <Button
          variant="primary"
          type="button"
          onClick={handlePrimary}
          disabled={busy || phase === "submitted"}
          aria-busy={busy}
        >
          {ctaLabel(phase)}
        </Button>
        {busy ? (
          <p className="state" role="status" aria-live="polite">
            Working on your request…
          </p>
        ) : null}
      </Card>
    </>
  );
}

function airportName(airports: readonly Airport[], id: string | null): string {
  if (!id) return "—";
  return airports.find((airport) => airport.id === id)?.name ?? "—";
}
