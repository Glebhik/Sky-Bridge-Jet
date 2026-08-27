# Phase 9.7.B — Operator Booking history and detail

Phase 9.7.B is based on `a5ebf861b89bbd12428330e0c02591fe96e8e204` and depends on the independently audited B0 read boundary. The Web application uses only `GET /api/v1/me/operator-bookings/history` and `GET /api/v1/me/operator-bookings/{booking_id}`; it never uses the generic trusted Booking detail.

The operator workspace preserves `/operator/bookings` as the actionable pending queue and adds `/operator/bookings/history` plus `/operator/bookings/{booking_id}`. Navigation remains Opportunities, Bookings and History. History uses bounded server pagination (`limit=10`, deterministic offsets) and canonical server-side status filtering. A detail GET occurs only after explicit navigation; history never performs per-row detail, Offer, Aircraft or Payment reads.

The closed same-origin proxy adds one exact history entry and one canonical-UUID detail pattern, both GET-only. Browser requests use same-origin credentials, `no-store`, AbortSignal and the selected `X-Organization-Id`. They contain no bearer token, upstream origin or browser-selected operator ID.

ADMIN, SALES, OPERATIONS, FINANCE and COMPLIANCE inherit `booking.read`. History and detail are read-only for every role; ADMIN/OPERATIONS decisions remain exclusively in the existing pending queue. Organization changes abort reads, increment a monotonic epoch, clear history/detail/errors and reject every late result, including an old first-A result after A→B→A.

The browser type mirrors `OperatorBookingReadView`: reference/status, own operator amount and currency, factual aircraft snapshot, safe legs and canonical lifecycle timestamps. It structurally excludes customer/passenger identity, requirements and notes; platform fee, tax decomposition and customer total; Payment/provider/idempotency/refund internals; and private decision/cancellation notes. Status copy describes Booking state only and never claims flight completion, payment, settlement or refund.

The UI provides loading, empty, safe error/404, manual refresh, filtering, pagination and unknown-status fallback states. Semantic headings, labelled controls, textual statuses, keyboard-operable links/buttons and responsive grid sizing cover 320–1440 px without color-only meaning.

Freshness is initial load plus explicit refresh/filter/page/detail navigation only: no polling, realtime transport or global subscription. Routes remain 92/88/4 and Alembic remains `20260827_0010`; there is no API, migration or dependency change. Cancellation/refund actions, passenger manifests, scheduling, dashboards and compliance-center expansion remain deferred.
