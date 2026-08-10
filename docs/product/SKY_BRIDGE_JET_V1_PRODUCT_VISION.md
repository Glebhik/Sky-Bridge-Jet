# Sky Bridge Jet V1 Product Vision

## Product statement

Sky Bridge Jet is a premium private aviation marketplace. It helps affluent
customers, executives, family offices, personal and executive assistants, and
concierge companies arrange private flights with qualified operators and
brokers. The experience must be premium, discreet, trustworthy, and extremely
easy to use.

It is not a generic travel website, airline ticket search engine, or flight
metasearch clone.

## Market and rollout

V1 is focused on Europe. Future expansion may include North America, South
America, Asia, Central Asia, Africa, and ultimately a global market. Geographic
expansion is a business decision, not an implicit product capability.

## Customer outcome

A customer should be able to express a request in natural language or a
structured form, for example:

> I need a private jet tomorrow after 14:00 from Dublin to Nice for four
> passengers, travelling with a small dog.

The product guides the request into complete, reviewable trip details; obtains
and compares appropriate operator offers; enables the customer to select an
offer; and provides clear booking and payment status. The journey must make
clear when a flight is requested, quoted, selected, pending confirmation, or
booked rather than implying guaranteed instant availability.

## Participants

```text
Customer or delegate
        |
Sky Bridge Jet
        |
Private jet operator / broker
        |
Aircraft and crew
        |
Airport / FBO
```

Sky Bridge Jet may also support concierge companies and authorized internal
administrators. Role-based access and delegated authority are fundamental:
customers, operators, concierges, and administrators must see only what their
authority permits.

## V1 core journey

1. An authorized customer, delegate, or concierge creates a trip request.
2. The request captures route, timing, passenger count, and relevant needs,
   such as pets, baggage, catering, or ground transfers.
3. Sky Bridge Jet and/or operators clarify incomplete details and identify
   suitable airports and aircraft categories.
4. Operators or brokers provide quotes with validity and commercial details.
5. The customer or authorized delegate compares and selects a quote.
6. The system creates and tracks the booking through confirmation, payment,
   travel, and completion as approved by the operating model.

V1 may use manual and semi-integrated operator workflows. It must not pretend
that live inventory or instant confirmation exists where it does not.

## Domain concepts

The anticipated core concepts are User, CustomerProfile, Passenger, Operator,
Aircraft, Airport, TripRequest, TripLeg, Quote, Booking, BookingPassenger,
EmptyLeg, PaymentRecord, and AuditEvent.

Aircraft categories may include very light, light, midsize, super midsize,
heavy, ultra-long-range, VIP airliner, and turboprop aircraft. Categories help
guide matching; actual suitability is subject to operator and operational
confirmation.

Trip requests progress from draft through submitted, quoting, quotes
available, quote selected, and booked, with cancellation and expiry where
appropriate. Quotes have their own validity and selection lifecycle. Bookings
move independently through confirmation, payment, travel, completion,
cancellation, and refund states. State changes must be explicit and auditable.

## Empty Legs

Empty legs are a strategic, first-class product concept. An empty leg is an
aircraft repositioning segment that may be offered to a customer, such as a
Geneva-to-London reposition after a Paris-to-Geneva charter.

It is not simply a discount flag. The product must retain its availability,
route, timing, constraints, source, validity, and withdrawal/expiry state.
An empty-leg opportunity still requires transparent availability and approved
quote/booking controls.

## Concierge and AI direction

The future natural-language concierge converts a request into a structured
Trip Request draft and identifies missing or ambiguous information. It is
vendor-neutral and must not depend on one LLM provider.

AI can assist understanding and preparation. It cannot autonomously create a
confirmed booking, initiate an irreversible financial action, or substitute for
required customer or authorized-human approval.

## Trust principles

- Be discreet with travel and passenger data.
- Be transparent about request, quote, confirmation, payment, and availability.
- Keep the customer in control of consequential decisions.
- Protect delegates, concierge relationships, and operator information through
  explicit authorization.
- Provide clear exception handling and human escalation for a premium service.
- Preserve auditability for commercial and sensitive actions.

## V1 boundary

V1 proves a European, web-first request-to-quote-to-booking experience with an
owner-approved operator and payment model. It does not include worldwide live
inventory, dispatch, crew scheduling, global real-time aircraft tracking,
native mobile apps, jet cards, fractional ownership, loyalty, cryptocurrency,
or autonomous AI commerce.
