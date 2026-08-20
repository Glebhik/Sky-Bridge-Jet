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

/** Customer-safe trip-request view (`/me/trip-requests` item). */
export interface CustomerTripRequest {
  readonly id: string;
  readonly status: string;
  readonly created_at: string;
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
