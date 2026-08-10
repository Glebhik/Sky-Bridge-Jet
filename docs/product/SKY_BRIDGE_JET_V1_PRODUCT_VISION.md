# Sky Bridge Jet V1 Product Vision

## Product statement

Sky Bridge Jet is a premium managed private-aviation marketplace and charter
intermediary. It helps affluent customers, executives, family offices, personal
and executive assistants, and concierge companies arrange private flights with
qualified operators and brokers. It provides the digital marketplace and
orchestration layer; it does not own or operate aircraft in V1, and licensed
operators remain responsible for flight operation and execution. The experience
must be premium, discreet, trustworthy, and extremely easy to use.

It is not a generic travel website, airline ticket search engine, or flight
metasearch clone.

## Market and rollout

V1 is Europe-first, prioritizing Ireland, the United Kingdom, France,
Monaco-area airports, Switzerland, Italy, Spain, Portugal, Germany, Austria,
the Netherlands, and Belgium. Country, currency, timezone, airport, operator,
and regulatory concepts remain globally extensible. Future expansion may
include North America, South America, Asia, Central Asia, Africa, and
ultimately a global market.

## Customer outcome

A customer should be able to express a request in natural language or a
structured form, for example:

> I need a private jet tomorrow after 14:00 from Dublin to Nice for four
> passengers, travelling with a small dog.

The product guides the request into complete, reviewable trip details; obtains
and compares appropriate operator offers; enables the customer to select an
offer; and provides clear booking and payment status. The journey must make
clear when a flight is requested, quoted, selected, awaiting operator
confirmation, payment-authorized, or booked rather than implying guaranteed
instant availability.

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
6. The operator confirms the selected offer.
7. The customer provides required payment authorization through an approved
   provider flow.
8. The system records a confirmed booking and tracks it through travel and
   completion as approved by the operating model.

This is the canonical V1 request-to-book flow. V1 may use manual and
semi-integrated operator workflows and must not pretend that live inventory or
instant confirmation exists where it does not. The architecture can later mark
an offer as instant-book-capable only when an approved provider offers reliable
real-time availability, pricing, and confirmation; full Instant Book is not a
V1 implementation commitment.

## Domain concepts

The anticipated core concepts are User, CustomerProfile, Passenger, Operator,
Aircraft, Airport, TripRequest, TripLeg, Quote, Booking, BookingPassenger,
EmptyLeg, PaymentRecord, and AuditEvent.

Aircraft categories may include very light, light, midsize, super midsize,
heavy, ultra-long-range, VIP airliner, and turboprop aircraft. Categories help
guide matching; actual suitability is subject to operator and operational
confirmation.

Trip requests progress from draft through submitted, quoting, quotes available,
and quote selected, with cancellation and expiry where appropriate. Quotes have
their own validity and selection lifecycle. Bookings move independently through
operator confirmation, payment/authorization, confirmed, travel, completion,
cancellation, and refund states. A selected quote is not a confirmed booking;
state changes must be explicit and auditable.

## Empty Legs

Empty legs are a strategic, first-class product concept. An empty leg is an
aircraft repositioning segment that may be offered to a customer, such as a
Geneva-to-London reposition after a Paris-to-Geneva charter.

It is not simply a discount flag. An Empty Leg independently records operator,
aircraft, origin, destination, departure window, available seats, price,
currency, flexibility, availability status, source, validity, and
withdrawal/expiry state. V1 may begin with seeded demo inventory, manually
entered operator inventory, or mock provider data, while preserving support for
future operator, broker, marketplace, and real-time inventory feeds. Customers
can discover and request/book eligible Empty Legs through the same transparent
confirmation and payment controls.

## Concierge and AI direction

The natural-language concierge is vendor-neutral and creates a structured Trip
Request draft, identifies missing information, searches and compares options,
recommends suitable aircraft categories, identifies Empty Leg opportunities,
prepares booking information, and assists concierge workflows. It must not
depend on one LLM provider.

AI can assist understanding and preparation. It cannot autonomously confirm a
legally binding booking, accept terms, authorize irreversible payment, bypass
operator confirmation, override compliance requirements, or substitute for
explicit authorized-user action.

Premium concierge is a core product direction. V1 captures relevant trip
requirements and has extensible service boundaries for chauffeur/ground
transport, FBO coordination, catering, pets, baggage, special assistance,
customer preferences, and destination ground services. It implements only the
concierge functions necessary to the private-jet booking journey, not a large
general-purpose concierge platform.

## Trust principles

- Be discreet with travel and passenger data.
- Be transparent about request, quote, confirmation, payment, and availability.
- Keep the customer in control of consequential decisions.
- Protect delegates, concierge relationships, and operator information through
  explicit authorization.
- Provide clear exception handling and human escalation for a premium service.
- Preserve auditability for commercial and sensitive actions.

## V1 boundary

V1 proves a Europe-first, web-first request-to-book experience with an
approved marketplace direction, operator confirmation, provider-bound payment
orchestration, scoped concierge requirements, and first-class Empty Leg
inventory. It does not include worldwide live inventory, dispatch, crew
scheduling, global real-time aircraft tracking, native mobile apps, jet cards,
fractional ownership, loyalty, cryptocurrency, escrow, banking, raw card
storage, complex settlement, multi-currency treasury, unverified
merchant-of-record assumptions, autonomous AI commerce, or full Instant Book
without an approved reliable provider integration. Legal characterization,
payment operations, and applicable regulatory obligations remain subject to
specialist review before production launch.
