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

/** The shared safe error envelope every API error uses: `{ error: { code, message } }`. */
export interface ApiErrorBody {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly details?: unknown;
  };
}
