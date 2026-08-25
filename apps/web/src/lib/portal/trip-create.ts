import { ApiError } from "@/lib/api/errors";
import type {
  Airport,
  CustomerTripRequest,
  PassengerCreateRequest,
  PassengerRecord,
  TripRequestCreateRequest,
} from "@/lib/api/types";

/**
 * Framework-free core of the Phase 9.3.B "create a trip request" journey: the form model,
 * client-side validation, payload builders, the airport-picker filter, safe error mapping,
 * and the idempotent creation orchestrator ({@link runCreation}). Keeping this logic out of
 * React makes the important guarantees directly unit-testable — that mutation payloads never
 * contain `customer_id`, that a retry never recreates already-created passengers or a DRAFT,
 * and that raw backend errors are never surfaced.
 */

/** The explicit lifecycle of a creation attempt, surfaced to the UI for honest states. */
export type CreationPhase =
  | "editing"
  | "creating_passengers"
  | "creating_trip"
  | "submitting_trip"
  | "submitted"
  | "passenger_error"
  | "trip_create_error"
  | "submit_error";

/** One passenger the customer typed in the form (there is no saved-passenger roster). */
export interface PassengerDraft {
  readonly first_name: string;
  readonly last_name: string;
  readonly date_of_birth: string;
  readonly nationality: string;
  readonly contact_email: string;
  readonly contact_phone: string;
}

/** The customer-facing requirements the create form collects (no pet UI in this slice). */
export interface RequirementsDraft {
  readonly baggage_notes: string;
  readonly catering_notes: string;
  readonly special_assistance_notes: string;
  readonly customer_notes: string;
  readonly ground_transport_requested: boolean;
}

/** The whole editable form model. A single journey leg (origin → destination → departure). */
export interface TripRequestForm {
  readonly origin_airport_id: string | null;
  readonly destination_airport_id: string | null;
  /** A `datetime-local` value (no timezone); normalized to a tz-aware ISO string on submit. */
  readonly departure_at_local: string;
  readonly passengers: readonly PassengerDraft[];
  readonly requirements: RequirementsDraft;
}

export function emptyPassenger(): PassengerDraft {
  return {
    first_name: "",
    last_name: "",
    date_of_birth: "",
    nationality: "",
    contact_email: "",
    contact_phone: "",
  };
}

export function emptyForm(): TripRequestForm {
  return {
    origin_airport_id: null,
    destination_airport_id: null,
    departure_at_local: "",
    passengers: [emptyPassenger()],
    requirements: {
      baggage_notes: "",
      catering_notes: "",
      special_assistance_notes: "",
      customer_notes: "",
      ground_transport_requested: false,
    },
  };
}

/** Field-scoped, client-convenience validation errors. Keyed by a stable field id. */
export type FieldErrors = Readonly<Record<string, string>>;

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Client-convenience validation only — the backend remains authoritative. Mirrors the exact
 * backend rules we can honestly check here: both airports selected and different, a valid
 * timezone-normalizable departure, and at least one passenger with a first and last name.
 */
export function validateForm(form: TripRequestForm): FieldErrors {
  const errors: Record<string, string> = {};
  if (!form.origin_airport_id || !UUID_RE.test(form.origin_airport_id)) {
    errors.origin = "Select a departure airport.";
  }
  if (
    !form.destination_airport_id ||
    !UUID_RE.test(form.destination_airport_id)
  ) {
    errors.destination = "Select a destination airport.";
  }
  if (
    form.origin_airport_id &&
    form.destination_airport_id &&
    form.origin_airport_id === form.destination_airport_id
  ) {
    errors.destination =
      "Destination must be different from the departure airport.";
  }
  if (normalizeDeparture(form.departure_at_local) === null) {
    errors.departure = "Enter a valid departure date and time.";
  }
  if (form.passengers.length === 0) {
    errors.passengers = "Add at least one passenger.";
  }
  form.passengers.forEach((passenger, index) => {
    if (passenger.first_name.trim().length === 0) {
      errors[`passenger.${index}.first_name`] = "First name is required.";
    }
    if (passenger.last_name.trim().length === 0) {
      errors[`passenger.${index}.last_name`] = "Last name is required.";
    }
  });
  return errors;
}

/**
 * Normalize a `datetime-local` value (local wall-clock, no zone) to a timezone-aware ISO
 * string in UTC, which the backend requires (`validate_aware_datetime`). Returns `null` for
 * an empty or unparseable value so the caller can render a field error rather than send junk.
 */
export function normalizeDeparture(local: string): string | null {
  if (local.trim().length === 0) return null;
  const date = new Date(local);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

/** Trim a form string, returning `null` for an empty result (the backend's optional shape). */
function optional(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length === 0 ? null : trimmed;
}

/**
 * Build the create-passenger payload. Crucially, this NEVER includes `customer_id`: the
 * server derives the owner from the session + active organization. Empty optional fields
 * collapse to `null`; nationality is upper-cased to the 2-letter country-code shape.
 */
export function buildPassengerPayload(
  draft: PassengerDraft,
): PassengerCreateRequest {
  const nationality = optional(draft.nationality);
  return {
    first_name: draft.first_name.trim(),
    last_name: draft.last_name.trim(),
    date_of_birth: optional(draft.date_of_birth),
    nationality: nationality ? nationality.toUpperCase() : null,
    contact_email: optional(draft.contact_email),
    contact_phone: optional(draft.contact_phone),
  };
}

/**
 * Build the create-DRAFT payload. Also NEVER includes `customer_id`. A single leg is derived
 * from the journey fields with `passenger_count` set to the real passenger roster size.
 */
export function buildTripPayload(
  form: TripRequestForm,
  passengerIds: readonly string[],
): TripRequestCreateRequest {
  const departure = normalizeDeparture(form.departure_at_local);
  if (
    !form.origin_airport_id ||
    !form.destination_airport_id ||
    departure === null
  ) {
    // Guarded by validateForm before we ever reach here; a defensive throw, not a fallback.
    throw new Error("Cannot build a trip payload from an invalid form.");
  }
  const req = form.requirements;
  return {
    legs: [
      {
        origin_airport_id: form.origin_airport_id,
        destination_airport_id: form.destination_airport_id,
        departure_at: departure,
        passenger_count: passengerIds.length,
      },
    ],
    passenger_ids: passengerIds,
    requirements: {
      baggage_notes: optional(req.baggage_notes),
      catering_notes: optional(req.catering_notes),
      special_assistance_notes: optional(req.special_assistance_notes),
      customer_notes: optional(req.customer_notes),
      ground_transport_requested: req.ground_transport_requested,
    },
  };
}

/**
 * Client-side airport filter for the picker. `GET /airports` has no server-side search
 * parameter (it returns all active airports), so matching happens here over the fields a
 * customer would recognise: name, city, IATA, ICAO. An empty query returns the first slice
 * so the list is never blank. Results are capped for a manageable, accessible list.
 */
export function filterAirports(
  airports: readonly Airport[],
  query: string,
  limit = 20,
): readonly Airport[] {
  const trimmed = query.trim().toLowerCase();
  if (trimmed.length === 0) return airports.slice(0, limit);
  const matches = airports.filter((airport) => {
    const haystack = [
      airport.name,
      airport.city,
      airport.iata_code ?? "",
      airport.icao_code,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(trimmed);
  });
  return matches.slice(0, limit);
}

/** A concise, human label for an airport option (never a fabricated code). */
export function airportOptionLabel(airport: Airport): string {
  const code = airport.iata_code ?? airport.icao_code;
  return `${airport.city} — ${airport.name} (${code})`;
}

// ── Safe error messages ──────────────────────────────────────────────────────────────────
// Never surface the raw backend message/code/body. Map only the statuses this flow can see.

export function messageForPassengerError(): string {
  return "We couldn’t save the passenger details. Please review them and try again.";
}

export function messageForTripCreateError(): string {
  return "We couldn’t create your trip request. Please try again.";
}

export function messageForSubmitError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "This request changed while it was being submitted. Refresh and try again.";
  }
  return "Your request was created, but we couldn’t submit it yet. Please try again.";
}

// ── Idempotent creation orchestrator ───────────────────────────────────────────────────────

/** The minimal API surface the orchestrator needs (injectable for tests). */
export interface CreationApi {
  createPassenger(
    body: PassengerCreateRequest,
    organizationId?: string,
    signal?: AbortSignal,
  ): Promise<PassengerRecord>;
  createTripRequest(
    body: TripRequestCreateRequest,
    organizationId?: string,
    signal?: AbortSignal,
  ): Promise<CustomerTripRequest>;
  submitTripRequest(
    id: string,
    expectedVersion: number,
    organizationId?: string,
    signal?: AbortSignal,
  ): Promise<CustomerTripRequest>;
}

/**
 * One passenger slot: the typed input plus the server id once created (null until then).
 * `input` stays mutable so a retry can pick up corrections to a not-yet-created passenger;
 * once `id` is set the slot is created and its input is never sent again.
 */
export interface PassengerSlot {
  input: PassengerDraft;
  id: string | null;
}

/**
 * The mutable progress of an in-flight (and possibly retried) creation. It is retained in
 * component memory across retries so a retry reuses already-created passengers and an
 * already-created DRAFT rather than duplicating them. It is intentionally NOT persisted to
 * any browser storage — a full reload legitimately loses it (documented limitation).
 */
export interface CreationProgress {
  readonly passengers: PassengerSlot[];
  readonly form: TripRequestForm;
  readonly organizationId?: string;
  draft: { id: string; version: number } | null;
}

/** Thrown when the backend response contradicts the expected state-machine invariant. */
export class CreationAssertionError extends Error {
  readonly phase: "trip_create" | "submit";
  constructor(phase: "trip_create" | "submit", message: string) {
    super(message);
    this.name = "CreationAssertionError";
    this.phase = phase;
  }
}

export function buildProgress(
  form: TripRequestForm,
  organizationId?: string,
): CreationProgress {
  return {
    passengers: form.passengers.map((input) => ({ input, id: null })),
    form,
    organizationId,
    draft: null,
  };
}

/**
 * Run (or resume) the create → submit journey against `progress`, mutating it in place so a
 * later retry with the SAME `progress` object continues where it left off:
 *
 *  1. create only passengers that do not yet have an id (reuse the rest);
 *  2. create the DRAFT only if one does not already exist, asserting `DRAFT`;
 *  3. submit that DRAFT with its version, asserting `SUBMITTED`.
 *
 * `onPhase` reports the phase being attempted so the caller can render honest state and map a
 * thrown error to the right partial-failure state. The final `SUBMITTED` trip is returned.
 */
export async function runCreation(
  api: CreationApi,
  progress: CreationProgress,
  onPhase: (phase: CreationPhase) => void,
  signal?: AbortSignal,
): Promise<CustomerTripRequest> {
  const needsPassengers = progress.passengers.some((slot) => slot.id === null);
  if (needsPassengers) {
    onPhase("creating_passengers");
    for (const slot of progress.passengers) {
      if (slot.id !== null) continue; // already created — never recreate on retry
      const created = await api.createPassenger(
        buildPassengerPayload(slot.input),
        progress.organizationId,
        signal,
      );
      slot.id = created.id;
    }
  }

  if (progress.draft === null) {
    onPhase("creating_trip");
    const passengerIds = progress.passengers.map((slot) => {
      if (slot.id === null) {
        throw new Error("Passenger id missing before trip creation.");
      }
      return slot.id;
    });
    const trip = await api.createTripRequest(
      buildTripPayload(progress.form, passengerIds),
      progress.organizationId,
      signal,
    );
    if (trip.status !== "DRAFT") {
      throw new CreationAssertionError(
        "trip_create",
        "Expected a DRAFT trip request.",
      );
    }
    progress.draft = { id: trip.id, version: trip.version };
  }

  onPhase("submitting_trip");
  const submitted = await api.submitTripRequest(
    progress.draft.id,
    progress.draft.version,
    progress.organizationId,
    signal,
  );
  if (submitted.status !== "SUBMITTED") {
    throw new CreationAssertionError(
      "submit",
      "Expected a SUBMITTED trip request.",
    );
  }
  // Keep the freshest version for any subsequent action on this same request.
  progress.draft = { id: submitted.id, version: submitted.version };
  onPhase("submitted");
  return submitted;
}
