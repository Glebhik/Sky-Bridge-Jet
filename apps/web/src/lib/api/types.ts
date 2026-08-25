/**
 * Browser-facing API contract types for the Customer Portal.
 *
 * These mirror the Phase 9.1.A customer-safe API schemas and the Phase 8 auth contracts.
 * Only customer-appropriate shapes live here — no operator/platform-only or internal
 * reconciliation types are exposed to portal components. `response_audience` on the shared
 * resource routes (ADR-046) is the customer literal, never the internal one.
 */

export type UserStatus =
  | "PENDING_VERIFICATION"
  | "ACTIVE"
  | "SUSPENDED"
  | "DISABLED";

export type OrganizationType = "CUSTOMER" | "OPERATOR" | "PLATFORM";

export interface User {
  readonly id: string;
  readonly email: string;
  readonly display_name: string | null;
  readonly status: UserStatus;
  readonly email_verified_at: string | null;
  readonly created_at: string;
}

/** A single organization membership as returned by `/auth/me` (never an org id alone). */
export interface Membership {
  readonly organization_id: string;
  readonly organization_type: OrganizationType;
  readonly role: string;
}

/** The `/auth/me` bootstrap contract (MeResponse). */
export interface MeResponse {
  readonly user: User;
  readonly memberships: readonly Membership[];
  readonly permissions: readonly string[];
}

/** The `/auth/register` request contract (Phase 9.2.A). Profile data is out of scope. */
export interface RegisterRequest {
  readonly email: string;
  readonly password: string;
}

/**
 * The `/auth/register` success contract (RegistrationResponse).
 *
 * `verification_token` is a development-only affordance the API returns solely outside
 * production (it is `null` in production, where delivery happens by email). Portal UI must
 * never depend on it; it exists here only to mirror the real contract.
 */
export interface RegistrationResponse {
  readonly user: User;
  readonly verification_token: string | null;
}

/** The `/auth/login` success contract (LoginResponse). */
export interface LoginResponse {
  readonly user: User;
  readonly csrf_token: string;
}

/** A generic single-message acknowledgement (MessageResponse). */
export interface MessageResponse {
  readonly message: string;
}

/** The `/auth/customer-account/recover` success contract (AccountRecoveryResponse). */
export interface AccountRecoveryResponse {
  readonly organization_id: string;
  readonly customer_id: string;
  readonly organization_type: OrganizationType;
  readonly role: string;
}

/** Customer-safe booking view (`/me/bookings` item) — no operator/platform split. */
export interface CustomerBooking {
  readonly id: string;
  readonly reference: string;
  readonly status: string;
  readonly currency: string;
  readonly total_amount_minor: number;
  readonly created_at: string;
}

/** One leg of a trip request (as returned by the customer trip-request read models). */
export interface TripLeg {
  readonly id: string;
  readonly sequence: number;
  readonly origin_airport_id: string;
  readonly destination_airport_id: string;
  readonly departure_at: string;
  readonly origin_timezone: string;
  readonly destination_timezone: string;
  readonly passenger_count: number;
}

/** A passenger attached to a trip request (the customer's own passenger, name only). */
export interface TripPassenger {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string;
}

/** Customer-supplied trip requirements (notes/flags only; no internal fields). */
export interface TripRequirements {
  readonly baggage_notes: string | null;
  readonly catering_notes: string | null;
  readonly ground_transport_requested: boolean;
  readonly special_assistance_notes: string | null;
  readonly customer_notes: string | null;
  readonly pet_present: boolean;
}

/**
 * Customer-safe trip-request view. Both `/me/trip-requests` (list) and
 * `/trip-requests/{id}` (detail) return this same shape; it mirrors the API's
 * `TripRequestResponse` and carries no operator/platform or internal-audit fields.
 */
export interface CustomerTripRequest {
  readonly id: string;
  readonly status: string;
  readonly version: number;
  readonly legs: readonly TripLeg[];
  readonly passengers: readonly TripPassenger[];
  readonly requirements: TripRequirements;
  readonly created_at: string;
  readonly updated_at: string;
}

/** Customer-safe published offer returned by the audience-discriminated trip offer list. */
export interface CustomerOffer {
  readonly id: string;
  readonly trip_request_id: string;
  readonly status: "SUBMITTED" | "EXPIRED" | "SELECTED";
  readonly currency: "EUR" | "GBP" | "USD";
  readonly total_amount_minor: number;
  readonly tax_amount_minor: number;
  readonly valid_until: string | null;
  readonly operator_legal_name: string;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly aircraft_category: string;
  readonly included_services: string | null;
  readonly excluded_services: string | null;
  readonly cancellation_policy: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly response_audience: "customer";
}

/** Public airport reference (`/airports/{id}`) — only the fields used to label a leg. */
export interface Airport {
  readonly id: string;
  readonly icao_code: string;
  readonly iata_code: string | null;
  readonly name: string;
  readonly city: string;
  readonly country_code: string;
}

/** Customer-safe payment-status view (`/me/payments` item) — status only. */
export interface CustomerPayment {
  readonly id: string;
  readonly booking_id: string;
  readonly status: string;
  readonly currency: string;
  readonly total_amount_minor: number;
  readonly created_at: string;
}

/**
 * Phase 9.3.B — customer *write* request contracts.
 *
 * These mirror the backend `PassengerCreate` / `TripRequestCreate` / `VersionedTripCommand`
 * schemas, with one deliberate omission: NONE of them carry `customer_id`. The browser neither
 * knows nor sends the internal customer UUID; the API derives the authoritative customer from
 * the authenticated principal plus the validated active organization (Phase 9.3.B0). A leaked
 * `customer_id` in any of these types would be a security regression, so it is absent by
 * construction and asserted by tests.
 */

/** Create-a-passenger request body. No `customer_id` — the server derives ownership. */
export interface PassengerCreateRequest {
  readonly first_name: string;
  readonly last_name: string;
  readonly date_of_birth?: string | null;
  readonly nationality?: string | null;
  readonly contact_email?: string | null;
  readonly contact_phone?: string | null;
}

/**
 * The customer-safe projection of a created passenger the browser actually consumes. The
 * backend `PassengerResponse` also echoes `customer_id`, but the portal never reads it: only
 * the returned `id` (used as a `passenger_id` in the trip payload) and the name are declared.
 */
export interface PassengerRecord {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string;
}

/** One leg of a create request (mirrors `TripLegCreate`). Airports are referenced by UUID. */
export interface TripLegCreateRequest {
  readonly origin_airport_id: string;
  readonly destination_airport_id: string;
  readonly departure_at: string;
  readonly passenger_count: number;
}

/** Customer-supplied requirements on create (mirrors `TripRequirementsCreate`; no pet UI). */
export interface TripRequirementsCreateRequest {
  readonly baggage_notes?: string | null;
  readonly catering_notes?: string | null;
  readonly ground_transport_requested: boolean;
  readonly special_assistance_notes?: string | null;
  readonly customer_notes?: string | null;
}

/** Create-a-DRAFT trip request body. No `customer_id` — the server derives ownership. */
export interface TripRequestCreateRequest {
  readonly legs: readonly TripLegCreateRequest[];
  readonly passenger_ids: readonly string[];
  readonly requirements: TripRequirementsCreateRequest;
}

/** The optimistic-concurrency command body for submit (mirrors `VersionedTripCommand`). */
export interface VersionedTripCommandRequest {
  readonly expected_version: number;
}

/** The shared safe error envelope every API error uses: `{ error: { code, message } }`. */
export interface ApiErrorBody {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly details?: unknown;
  };
}
