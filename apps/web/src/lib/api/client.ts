import { ApiError, apiErrorFromResponse } from "@/lib/api/errors";
import type {
  AccountRecoveryResponse,
  Airport,
  BookingCreateRequest,
  CustomerBooking,
  CustomerOffer,
  CustomerPayment,
  CustomerPaymentInitiation,
  CustomerPaymentInitiateRequest,
  CustomerTripRequest,
  LoginResponse,
  MeResponse,
  MessageResponse,
  PassengerCreateRequest,
  PassengerRecord,
  RegistrationResponse,
  TripRequestCreateRequest,
  User,
  OperatorBooking,
  OperatorBookingDecisionResponse,
  BookingRejectionReason,
} from "@/lib/api/types";

/**
 * The browser-side typed API client. It talks ONLY to the web app's own origin via the
 * same-origin proxy (`/api/proxy/...`); it never knows the upstream API host. Session
 * cookies ride along automatically (`credentials: "same-origin"`) and mutations attach the
 * readable CSRF cookie as the `X-CSRF-Token` header. Every failure surfaces as a typed
 * {@link ApiError} that preserves the upstream status (401/403/409/429/5xx) — nothing is
 * silently swallowed or coerced to success.
 */

const PROXY_BASE = "/api/proxy";
// Matches the API's default readable CSRF cookie (double-submit). Server-side validation
// compares it to the session's stored secret, so this is only the transport.
const CSRF_COOKIE = "sbj_csrf";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type Query = Record<string, string | number | readonly string[] | undefined>;

interface RequestOptions {
  readonly method?: string;
  readonly body?: unknown;
  readonly query?: Query;
  readonly signal?: AbortSignal;
  /** The validated active customer-organization id, sent as `X-Organization-Id`. */
  readonly organizationId?: string;
}

function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function buildPath(path: string, query?: Query): string {
  const url = new URL(`${PROXY_BASE}/${path}`, "http://portal.local");
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, item);
      } else if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return `${url.pathname}${url.search}`;
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    // A non-JSON body where JSON was expected is a malformed contract, not a value.
    if (response.ok) {
      throw new ApiError(
        response.status,
        "malformed_response",
        "Malformed response.",
        "malformed",
      );
    }
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiError(
      response.status,
      "malformed_response",
      "Malformed response.",
      "malformed",
    );
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers({ accept: "application/json" });
  let body: string | undefined;
  if (options.body !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(options.body);
  }
  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCsrfToken();
    if (csrf !== null) headers.set("x-csrf-token", csrf);
  }
  if (options.organizationId !== undefined) {
    headers.set("x-organization-id", options.organizationId);
  }

  let response: Response;
  try {
    response = await fetch(buildPath(path, options.query), {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "network_error",
      "Unable to reach the service.",
      "network",
    );
  }

  const parsed = await parseBody(response);
  if (!response.ok) {
    throw apiErrorFromResponse(response.status, parsed);
  }
  return parsed as T;
}

export const portalApi = {
  getMe: (signal?: AbortSignal) =>
    apiRequest<MeResponse>("auth/me", { signal }),
  register: (email: string, password: string, signal?: AbortSignal) =>
    apiRequest<RegistrationResponse>("auth/register", {
      method: "POST",
      body: { email, password },
      signal,
    }),
  verifyEmail: (token: string, signal?: AbortSignal) =>
    apiRequest<User>("auth/verify-email", {
      method: "POST",
      body: { token },
      signal,
    }),
  resendVerification: (email: string, signal?: AbortSignal) =>
    apiRequest<MessageResponse>("auth/verification/resend", {
      method: "POST",
      body: { email },
      signal,
    }),
  login: (email: string, password: string, signal?: AbortSignal) =>
    apiRequest<LoginResponse>("auth/login", {
      method: "POST",
      body: { email, password },
      signal,
    }),
  requestPasswordReset: (email: string, signal?: AbortSignal) =>
    apiRequest<MessageResponse>("auth/password-reset", {
      method: "POST",
      body: { email },
      signal,
    }),
  confirmPasswordReset: (
    token: string,
    password: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<MessageResponse>("auth/password-reset/confirm", {
      method: "POST",
      body: { token, password },
      signal,
    }),
  logout: (signal?: AbortSignal) =>
    apiRequest<MessageResponse>("auth/logout", { method: "POST", signal }),
  recoverCustomerAccount: (signal?: AbortSignal) =>
    apiRequest<AccountRecoveryResponse>("auth/customer-account/recover", {
      method: "POST",
      signal,
    }),
  listTripRequests: (organizationId?: string, signal?: AbortSignal) =>
    apiRequest<readonly CustomerTripRequest[]>("me/trip-requests", {
      organizationId,
      signal,
    }),
  getTripRequest: (id: string, organizationId?: string, signal?: AbortSignal) =>
    apiRequest<CustomerTripRequest>(`trip-requests/${id}`, {
      organizationId,
      signal,
    }),
  listTripRequestOffers: (
    tripRequestId: string,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<readonly CustomerOffer[]>(
      `trip-requests/${tripRequestId}/offers`,
      { organizationId, signal },
    ),
  selectOffer: (
    tripRequestId: string,
    offerId: string,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerOffer>(
      `trip-requests/${tripRequestId}/offers/${offerId}/select`,
      { method: "POST", organizationId, signal },
    ),
  getAirport: (id: string, signal?: AbortSignal) =>
    apiRequest<Airport>(`airports/${id}`, { signal }),
  // Phase 9.3.B write journey. Each mutation goes through the same same-origin proxy, carries
  // the readable CSRF cookie as a header (via apiRequest), and forwards the validated active
  // organization so the API can derive the authoritative customer. NONE send `customer_id`.
  //
  // The airport picker uses `listAirports` (the real `GET /airports` contract, which takes no
  // query parameters and returns all active airports); filtering/search happens client-side.
  listAirports: (signal?: AbortSignal) =>
    apiRequest<readonly Airport[]>("airports", { signal }),
  createPassenger: (
    body: PassengerCreateRequest,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<PassengerRecord>("passengers", {
      method: "POST",
      body,
      organizationId,
      signal,
    }),
  createTripRequest: (
    body: TripRequestCreateRequest,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerTripRequest>("trip-requests", {
      method: "POST",
      body,
      organizationId,
      signal,
    }),
  submitTripRequest: (
    id: string,
    expectedVersion: number,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerTripRequest>(`trip-requests/${id}/submit`, {
      method: "POST",
      body: { expected_version: expectedVersion },
      organizationId,
      signal,
    }),
  // Phase 9.3.C. Cancel the customer's own trip request with the optimistic version it was
  // last read at. Same proxy/CSRF/org conventions as submit; no customer_id, no storage.
  cancelTripRequest: (
    id: string,
    expectedVersion: number,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerTripRequest>(`trip-requests/${id}/cancel`, {
      method: "POST",
      body: { expected_version: expectedVersion },
      organizationId,
      signal,
    }),
  listBookings: (organizationId?: string, signal?: AbortSignal) =>
    apiRequest<readonly CustomerBooking[]>("me/bookings", {
      organizationId,
      signal,
    }),
  createBooking: (
    body: BookingCreateRequest,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerBooking>("bookings", {
      method: "POST",
      body,
      organizationId,
      signal,
    }),
  getTripRequestBooking: (
    tripRequestId: string,
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerBooking>(`trip-requests/${tripRequestId}/booking`, {
      organizationId,
      signal,
    }),
  listPayments: (
    bookingIds: readonly string[],
    organizationId?: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<readonly CustomerPayment[]>("me/payments", {
      query: { booking_id: bookingIds },
      organizationId,
      signal,
    }),
  initiatePayment: (
    bookingId: string,
    body: CustomerPaymentInitiateRequest,
    organizationId: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<CustomerPaymentInitiation>(
      `bookings/${bookingId}/payment/initiate`,
      {
        method: "POST",
        body,
        organizationId,
        signal,
      },
    ),
  listOperatorBookings: (organizationId: string, signal?: AbortSignal) =>
    apiRequest<readonly OperatorBooking[]>("me/operator-bookings", {
      organizationId,
      signal,
    }),
  confirmOperatorBooking: (
    bookingId: string,
    body: { readonly confirmation_reference?: string; readonly note?: string },
    organizationId: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<OperatorBookingDecisionResponse>(
      `bookings/${bookingId}/confirm`,
      {
        method: "POST",
        body,
        organizationId,
        signal,
      },
    ),
  rejectOperatorBooking: (
    bookingId: string,
    body: { readonly reason: BookingRejectionReason; readonly note?: string },
    organizationId: string,
    signal?: AbortSignal,
  ) =>
    apiRequest<OperatorBookingDecisionResponse>(
      `bookings/${bookingId}/reject`,
      {
        method: "POST",
        body,
        organizationId,
        signal,
      },
    ),
};
