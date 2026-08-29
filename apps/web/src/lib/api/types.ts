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

export type AdmissionStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "SUSPENDED";
export type EvidenceStatus =
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "VERIFIED"
  | "REJECTED"
  | "SUPERSEDED";
export type AuthorizationStatus = AdmissionStatus;

export interface PlatformAdmission {
  readonly id: string;
  readonly operator_id: string;
  readonly operator_legal_name: string;
  readonly operator_trading_name: string | null;
  readonly operator_country_code: string;
  readonly status: AdmissionStatus;
  readonly reason_code: string | null;
  readonly review_note: string | null;
  readonly submitted_at: string | null;
  readonly reviewed_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface PlatformEvidence {
  readonly id: string;
  readonly operator_id: string;
  readonly operator_legal_name: string;
  readonly operator_trading_name: string | null;
  readonly aircraft_id: string | null;
  readonly aircraft_registration: string | null;
  readonly evidence_type: string;
  readonly status: EvidenceStatus;
  readonly effective_status: string;
  readonly authority_basis: string | null;
  readonly reference_number: string | null;
  readonly issuing_authority: string | null;
  readonly jurisdiction: string | null;
  readonly insurer_name: string | null;
  readonly has_storage_object: boolean;
  readonly effective_date: string | null;
  readonly expiry_date: string | null;
  readonly submitted_at: string | null;
  readonly reviewed_at: string | null;
  readonly review_reason_code: string | null;
  readonly review_note: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface PlatformAuthorization {
  readonly id: string;
  readonly operator_id: string;
  readonly operator_legal_name: string;
  readonly operator_trading_name: string | null;
  readonly aircraft_id: string;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly status: AuthorizationStatus;
  readonly authority_basis: string;
  readonly reason_code: string | null;
  readonly review_note: string | null;
  readonly submitted_at: string | null;
  readonly reviewed_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ComplianceAuditEvent {
  readonly id: string;
  readonly action: string;
  readonly previous_status: string | null;
  readonly new_status: string | null;
  readonly actor_type: string;
  readonly actor_reference: string | null;
  readonly reason_code: string | null;
  readonly note: string | null;
  readonly created_at: string;
}

export interface PlatformReviewCommand {
  readonly action: string;
  readonly reason_code?: string;
  readonly note?: string;
}

export type PaymentOperationType = "AUTHORIZE" | "CAPTURE" | "VOID" | "REFUND";
export type PaymentOperationResult =
  | "PENDING"
  | "UNKNOWN"
  | "FAILED"
  | "SUCCEEDED";

export interface PlatformPaymentOperation {
  readonly id: string;
  readonly payment_id: string;
  readonly operation: PaymentOperationType;
  readonly result: PaymentOperationResult;
  readonly amount_minor: number;
  readonly provider_kind: "FAKE" | "STRIPE";
  readonly provider_reference: string | null;
  readonly failure_code: string | null;
  readonly correlation_id: string;
  readonly attempt_count: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface PlatformPaymentException extends PlatformPaymentOperation {
  readonly booking_id: string;
  readonly payment_reference: string;
  readonly payment_status: string;
  readonly currency: string;
  readonly total_amount_minor: number;
  readonly authorized_amount_minor: number | null;
  readonly captured_amount_minor: number;
  readonly refunded_amount_minor: number;
  readonly can_reconcile: boolean;
}

export interface PlatformPaymentDetail {
  readonly id: string;
  readonly reference: string;
  readonly booking_id: string;
  readonly status: string;
  readonly currency: string;
  readonly payment_provider: "FAKE" | "STRIPE";
  readonly operator_amount_minor: number;
  readonly platform_fee_minor: number;
  readonly tax_amount_minor: number;
  readonly total_amount_minor: number;
  readonly authorized_amount_minor: number | null;
  readonly captured_amount_minor: number;
  readonly refunded_amount_minor: number;
  readonly provider_payment_reference: string | null;
  readonly provider_status: string | null;
  readonly requires_customer_action: boolean;
  readonly authorized_at: string | null;
  readonly captured_at: string | null;
  readonly cancelled_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly operations: readonly PlatformPaymentOperation[];
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

export type CustomerBookingStatus =
  | "PENDING_OPERATOR_CONFIRMATION"
  | "CONFIRMED"
  | "REJECTED"
  | "CANCELLED";

/** Customer-safe booking view — no internal identifiers, commercial split, or notes. */
export interface CustomerBooking {
  readonly id: string;
  readonly reference: string;
  readonly trip_request_id: string;
  readonly operator_offer_id: string;
  readonly status: CustomerBookingStatus;
  readonly currency: string;
  readonly total_amount_minor: number;
  readonly tax_amount_minor: number;
  readonly operator_legal_name: string;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly aircraft_category: string;
  readonly confirmed_at: string | null;
  readonly cancelled_at: string | null;
  readonly cancellation_actor: "CUSTOMER" | "OPERATOR" | "PLATFORM" | null;
  readonly cancellation_reason:
    | "SCHEDULE_CHANGE"
    | "NO_LONGER_REQUIRED"
    | "OPERATOR_UNAVAILABLE"
    | "OTHER"
    | null;
  readonly created_at: string;
  readonly updated_at: string;
}

/** Customer Booking creation authority consists only of the selected trip and offer. */
export interface BookingCreateRequest {
  readonly trip_request_id: string;
  readonly operator_offer_id: string;
}

export type OperatorBookingStatus =
  | "PENDING_OPERATOR_CONFIRMATION"
  | "CONFIRMED"
  | "REJECTED"
  | "CANCELLED";

export interface OperatorBookingLeg {
  readonly sequence: number;
  readonly origin_airport_code: string;
  readonly destination_airport_code: string;
  readonly departure_at: string;
  readonly passenger_count: number;
}

/** Minimal operator-safe queue item: deliberately no customer, fee, payment, or notes. */
export interface OperatorBooking {
  readonly booking_id: string;
  readonly reference: string;
  readonly status: OperatorBookingStatus;
  readonly trip_request_id: string;
  readonly operator_offer_id: string;
  readonly currency: "EUR" | "GBP" | "USD";
  readonly operator_amount_minor: number;
  readonly operator_legal_name: string;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly aircraft_category: string;
  readonly legs: readonly OperatorBookingLeg[];
  readonly created_at: string;
}

/** B0 history/detail projection. Deliberately excludes customer and payment data. */
export interface OperatorBookingReadView {
  readonly id: string;
  readonly reference: string;
  readonly status: OperatorBookingStatus;
  readonly trip_request_id: string;
  readonly operator_offer_id: string;
  readonly aircraft_id: string;
  readonly currency: "EUR" | "GBP" | "USD";
  readonly operator_amount_minor: number;
  readonly operator_legal_name: string;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly aircraft_category: string;
  readonly legs: readonly OperatorBookingLeg[];
  readonly confirmed_at: string | null;
  readonly rejected_at: string | null;
  readonly cancelled_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export type BookingRejectionReason =
  | "AIRCRAFT_UNAVAILABLE"
  | "SCHEDULE_CONFLICT"
  | "OPERATIONAL_RESTRICTION"
  | "COMMERCIAL_WITHDRAWAL"
  | "OTHER";

export interface OperatorBookingDecisionResponse {
  readonly id: string;
  readonly status: OperatorBookingStatus;
}

export type FlightOperationStatus = "HANDOFF_CREATED";

export interface OperatorFlightOperationLeg {
  readonly sequence: number;
  readonly origin_airport_code: string;
  readonly destination_airport_code: string;
  readonly departure_at: string;
  readonly passenger_count: number;
}

/** D0 operator-safe projection: no customer, passenger identity, or financial data. */
export interface OperatorFlightOperation {
  readonly operation_id: string;
  readonly booking_id: string;
  readonly booking_reference: string;
  readonly status: FlightOperationStatus;
  readonly booking_status: OperatorBookingStatus;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly aircraft_category: string;
  readonly legs: readonly OperatorFlightOperationLeg[];
  readonly created_at: string;
  readonly updated_at: string;
}

export type OperatorOfferStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "SELECTED"
  | "WITHDRAWN"
  | "EXPIRED";

export interface OperatorOpportunityLeg {
  readonly sequence: number;
  readonly origin_airport_code: string;
  readonly destination_airport_code: string;
  readonly departure_at: string;
  readonly passenger_count: number;
}

export interface OperatorOpportunity {
  readonly trip_request_id: string;
  readonly status: "SUBMITTED";
  readonly legs: readonly OperatorOpportunityLeg[];
  readonly own_offers: readonly {
    readonly offer_id: string;
    readonly status: OperatorOfferStatus;
  }[];
  readonly created_at: string;
}

export interface OperatorAircraft {
  readonly id: string;
  readonly registration: string;
  readonly manufacturer: string;
  readonly model: string;
  readonly category: string;
  readonly passenger_capacity: number;
  readonly status: string;
  readonly eligible: boolean;
}

export interface OperatorAircraftCreate {
  readonly registration: string;
  readonly manufacturer: string;
  readonly model: string;
  readonly category: string;
  readonly passenger_capacity: number;
}

export type OperatorAdmissionStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "SUSPENDED";

export type EligibilityReasonCode =
  | "OPERATOR_NOT_ADMITTED"
  | "OPERATOR_UNDER_REVIEW"
  | "OPERATOR_REJECTED"
  | "OPERATOR_SUSPENDED"
  | "AUTHORITY_NOT_VERIFIED"
  | "AUTHORITY_EXPIRED"
  | "INSURANCE_NOT_VERIFIED"
  | "INSURANCE_EXPIRED"
  | "AIRCRAFT_NOT_AUTHORIZED"
  | "AIRCRAFT_AUTHORIZATION_SUSPENDED"
  | "AIRCRAFT_NOT_OPERATED_BY_OPERATOR";

/** Exact C0 operator-safe projection. No evidence, review, or internal identity fields. */
export interface OperatorComplianceReadiness {
  readonly admission_status: OperatorAdmissionStatus | null;
  readonly marketplace_eligible: boolean;
  readonly blockers: readonly EligibilityReasonCode[];
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

export interface OperatorOfferCommand {
  readonly currency?: "EUR" | "GBP" | "USD";
  readonly operator_amount_minor?: number;
  readonly tax_amount_minor?: number;
  readonly valid_until?: string | null;
  readonly operator_notes?: string | null;
  readonly cancellation_policy?: string | null;
  readonly included_services?: string | null;
  readonly excluded_services?: string | null;
}

export interface OperatorOfferCreate extends OperatorOfferCommand {
  readonly trip_request_id: string;
  readonly aircraft_id: string;
  readonly currency: "EUR" | "GBP" | "USD";
  readonly operator_amount_minor: number;
}

/** Operator workspace view. Components deliberately omit fee, customer total and payments. */
export interface OperatorOffer {
  readonly id: string;
  readonly trip_request_id: string;
  readonly aircraft_id: string;
  readonly status: OperatorOfferStatus;
  readonly currency: "EUR" | "GBP" | "USD";
  readonly operator_amount_minor: number;
  readonly tax_amount_minor: number;
  readonly valid_until: string | null;
  readonly aircraft_registration: string;
  readonly aircraft_manufacturer: string;
  readonly aircraft_model: string;
  readonly aircraft_category: string;
  readonly operator_notes: string | null;
  readonly cancellation_policy: string | null;
  readonly included_services: string | null;
  readonly excluded_services: string | null;
  readonly created_at: string;
  readonly updated_at: string;
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
  readonly authorized_amount_minor: number | null;
  readonly captured_amount_minor: number;
  readonly refunded_amount_minor: number;
  readonly requires_customer_action: boolean;
  readonly authorized_at: string | null;
  readonly captured_at: string | null;
  readonly cancelled_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

/** The only customer-supplied field accepted by the B0 authorization boundary. */
export interface CustomerPaymentInitiateRequest {
  readonly idempotency_key: string;
}

export interface CustomerPaymentClientAction {
  readonly action_type: "stripe_confirm_payment";
  readonly client_secret: string;
}

export interface CustomerPaymentInitiation extends CustomerPayment {
  readonly client_action?: CustomerPaymentClientAction | null;
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
