# Phase 9.4 — Offers Visual Polish V1

Canonical base: `a3475789a6be5aa965f2d49947543ec21a97dbf3` (post-merge Phase 9.4.C plus CI hotfix).

This slice is visual-only. It does not start Phase 9.5 and does not change offer publication, reads, selection, freshness, money, or eligibility.

## Purpose

Elevate the complete customer Offers experience into the already-merged Midnight Aviation Customer Portal visual language: dark midnight/navy surfaces, restrained champagne accents, ivory text, and quiet private-aviation hierarchy. Auth and `/demo` are out of scope.

Grok scope only. No architecture redesign. No invented commercial claims.

## Surfaces polished

- `/portal/offers` trip-centric landing
- Offer comparison inside `/portal/trip-requests/[id]`
- Available, expired, selected, unavailable cards
- Loading, empty, and isolated error states
- Manual refresh and transient last-known warning
- Select offer CTA, confirmation panel, pending selection, and 409 refresh presentation
- Mixed-currency comparison layout
- Mobile stacking of offer cards and confirmation controls

## Midnight Aviation direction

Portal tokens remain scoped under `.portal` (midnight, navy, champagne, ivory, muted graphite). Champagne is used for:

- available/selected marks and selected card border
- price currency label
- primary Select actions
- focus

It is not used as a marketplace gold wash. Selected is calm commercial intent, not a ticket, booking, or payment confirmation. Expired is subdued and still readable. Available is actionable without urgency language.

## Factual offer hierarchy

Each card keeps the real customer-safe fields in this visual order:

1. Currency code + formatted total (`formatOfferMoney`)
2. Textual status (`Available` / `Selected` / `Expired` / `Unavailable`)
3. Operator legal name
4. Aircraft snapshot (manufacturer, model, category, registration)
5. Validity
6. Tax included (same formatter, same currency)
7. Included / excluded services
8. Cancellation policy
9. Select offer, only when `canSelectCustomerOffer` already allows it

No ranking, cheapest, recommended, savings, FX conversion, or installment language.

## Selected / expired styling

- Selected: champagne border, quiet champagne wash, filled mark, badge text `Selected`. TripRequest remains `SUBMITTED`.
- Expired / unavailable: muted mark and badge text; factual price/operator/aircraft remain visible; no Select CTA.
- Status is never colour-only.

## Freshness styling

Polling, AbortController, generation guard, hidden pause, focus/visibility refresh, and the 30_000 ms cadence are unchanged. Visual-only:

- Manual **Refresh offers** is a quiet ghost control
- Background refresh does not replace the grid with a full-section loader
- Transient warning keeps the existing copy: “Couldn’t refresh offers. Showing the last known information.”

## Confirmation styling

Existing copy and actions are locked:

- Choosing this offer records commercial intent
- No Booking is created
- No charge occurs
- Selection cannot currently be changed
- **Keep comparing** / **Select this offer** / **Selecting…**

The panel is a premium in-flow decision surface, not a checkout modal, payment sheet, or destructive alert.

## Accessibility

Preserved: semantic headings, native buttons, `aria-label` on offer articles, `aria-busy` on the grid and confirmation, live-region behaviour of existing alerts, `aria-hidden` decorative marks. Focus-visible champagne ring and `prefers-reduced-motion` remain portal-wide. No extra ARIA.

## Responsive verification

Required viewports: 320×568, 390×844, 768×1024, 1024×768, 1440×900.

Cards stack to one column below 48rem, two columns from tablet, auto-fit on wide desktop. Price, currency, operator, aircraft, services, and cancellation policy wrap. Confirmation and refresh controls stay at ≥44px touch targets. Portal mobile navigation is unchanged.

## Functional locks (unchanged)

- `/portal/offers` uses `listTripRequests` only — no N+1, no `listTripRequestOffers`
- Trip-detail offers remain `portalApi.listTripRequestOffers`
- `OFFER_REFRESH_INTERVAL_MS === 30_000`
- Hidden pause, focus refresh, visibility refresh
- AbortController, generation guard, one in-flight GET
- Select Offer is a no-body POST with the existing duplicate guard
- 409 is an explicit refresh, never an automatic mutation retry
- Selected lock; TripRequest stays `SUBMITTED`
- Booking = 0, Payment = 0
- `apps/api/**`, proxy, route policy, polling state machine, money/order/eligibility helpers: zero functional diff

## Deferred

Phase 9.5 Booking. Payments. Operator/admin. Any change to freshness cadence or selection semantics.
