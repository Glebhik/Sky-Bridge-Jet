from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.core_aviation.models import TripRequest
from sky_bridge_jet.modules.iam.domain import (
    ROLE_PERMISSIONS,
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    Permission,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership, User
from sky_bridge_jet.modules.notifications.delivery import (
    MarketplaceEmail,
    MarketplaceNotificationSender,
    NotificationDeliveryError,
)
from sky_bridge_jet.modules.notifications.domain import (
    MarketplaceNotificationEvent,
    NotificationFailureCode,
    RecipientFanoutError,
)
from sky_bridge_jet.modules.notifications.models import NotificationOutbox
from sky_bridge_jet.modules.notifications.repositories import NotificationOutboxRepository
from sky_bridge_jet.modules.notifications.services import NotificationOutboxService
from sky_bridge_jet.modules.offers.domain import EffectiveOfferStatus, effective_offer_status
from sky_bridge_jet.modules.offers.models import OperatorOffer

MAX_NOTIFICATION_RECIPIENTS = 100
MAX_DISPATCH_BATCH = 100
CLAIM_LEASE = timedelta(minutes=10)
MAX_DELIVERY_ATTEMPTS = 3
RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=30))

_CUSTOMER_ROLES = tuple(
    role
    for role in (OrganizationRole.CUSTOMER_OWNER, OrganizationRole.CUSTOMER_ASSISTANT)
    if Permission.BOOKING_READ in ROLE_PERMISSIONS[role]
)
_OPERATOR_DECIDER_ROLES = tuple(
    role
    for role in (OrganizationRole.OPERATOR_ADMIN, OrganizationRole.OPERATOR_OPERATIONS)
    if Permission.BOOKING_DECIDE in ROLE_PERMISSIONS[role]
)


@dataclass(frozen=True)
class ClaimedNotification:
    id: UUID
    claim_token: UUID
    event: MarketplaceNotificationEvent | None
    recipient_user_id: UUID
    resource_type: str
    resource_id: UUID
    attempt_count: int


@dataclass(frozen=True)
class RecipientContext:
    user_id: UUID
    email: str


@dataclass(frozen=True)
class DispatchResult:
    claimed: int
    delivered: int
    retryable_failed: int
    permanent_failed: int
    stale_results: int


class MarketplaceNotificationService:
    """Create trusted notification intents inside the caller's business transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.outbox = NotificationOutboxService(session)

    def record_offer_available(self, offer_id: UUID, customer_id: UUID) -> list[NotificationOutbox]:
        return self._record_for_customer(
            MarketplaceNotificationEvent.OFFER_AVAILABLE,
            resource_type="OFFER",
            resource_id=offer_id,
            customer_id=customer_id,
        )

    def record_booking_pending(
        self, booking_id: UUID, operator_id: UUID
    ) -> list[NotificationOutbox]:
        recipients = self._organization_recipients(
            organization_type=OrganizationType.OPERATOR,
            linked_id=operator_id,
            roles=_OPERATOR_DECIDER_ROLES,
        )
        return self._record(
            MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION,
            "BOOKING",
            booking_id,
            recipients,
        )

    def record_booking_confirmed(
        self, booking_id: UUID, customer_id: UUID
    ) -> list[NotificationOutbox]:
        return self._record_for_customer(
            MarketplaceNotificationEvent.BOOKING_CONFIRMED,
            resource_type="BOOKING",
            resource_id=booking_id,
            customer_id=customer_id,
        )

    def record_booking_rejected(
        self, booking_id: UUID, customer_id: UUID
    ) -> list[NotificationOutbox]:
        return self._record_for_customer(
            MarketplaceNotificationEvent.BOOKING_REJECTED,
            resource_type="BOOKING",
            resource_id=booking_id,
            customer_id=customer_id,
        )

    def _record_for_customer(
        self,
        event: MarketplaceNotificationEvent,
        *,
        resource_type: str,
        resource_id: UUID,
        customer_id: UUID,
    ) -> list[NotificationOutbox]:
        recipients = self._organization_recipients(
            organization_type=OrganizationType.CUSTOMER,
            linked_id=customer_id,
            roles=_CUSTOMER_ROLES,
        )
        return self._record(event, resource_type, resource_id, recipients)

    def _organization_recipients(
        self,
        *,
        organization_type: OrganizationType,
        linked_id: UUID,
        roles: tuple[OrganizationRole, ...],
    ) -> list[UUID]:
        linked_column = (
            Organization.customer_id
            if organization_type is OrganizationType.CUSTOMER
            else Organization.operator_id
        )
        statement = (
            select(User.id)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .join(Organization, Organization.id == OrganizationMembership.organization_id)
            .where(
                Organization.organization_type == organization_type,
                linked_column == linked_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
                OrganizationMembership.role.in_(roles),
                User.status == UserStatus.ACTIVE,
                User.email_verified_at.is_not(None),
            )
            .distinct()
            .order_by(User.id)
            .limit(MAX_NOTIFICATION_RECIPIENTS + 1)
        )
        recipients = list(self.session.scalars(statement))
        if len(recipients) > MAX_NOTIFICATION_RECIPIENTS:
            raise RecipientFanoutError("Notification recipient policy exceeds the bounded maximum")
        return recipients

    def _record(
        self,
        event: MarketplaceNotificationEvent,
        resource_type: str,
        resource_id: UUID,
        recipients: list[UUID],
    ) -> list[NotificationOutbox]:
        return [
            self.outbox.create_intent(
                dedupe_key=f"{event.value}:{resource_id}:{recipient_id}",
                event_type=event.value,
                recipient_user_id=recipient_id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            for recipient_id in recipients
        ]


class MarketplaceNotificationDispatcher:
    """Bounded, restart-safe delivery orchestrator over the merged C0 primitives."""

    def __init__(
        self,
        session: Session,
        sender: MarketplaceNotificationSender,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.sender = sender
        self.settings = settings or get_settings()

    def dispatch_batch(self, *, now: datetime, limit: int = 20) -> DispatchResult:
        if limit < 1 or limit > MAX_DISPATCH_BATCH:
            raise ValueError(f"limit must be between 1 and {MAX_DISPATCH_BATCH}")
        with self.session.begin():
            claimed_rows = NotificationOutboxRepository(self.session).claim_batch(
                now=now,
                lease_expires_before=now - CLAIM_LEASE,
                limit=limit,
            )
            claimed = [self._snapshot(row) for row in claimed_rows]
        with self.session.begin():
            recipients = self._resolve_recipients(claimed)
            applicable_ids = self._applicable_notification_ids(claimed, now=now)

        delivered = retryable_failed = permanent_failed = stale_results = 0
        for notification in claimed:
            if notification.event is None:
                if self._mark_failed(
                    notification,
                    now=now,
                    retryable=False,
                    code=NotificationFailureCode.TEMPLATE_ERROR,
                ):
                    permanent_failed += 1
                else:
                    stale_results += 1
                continue
            recipient = recipients.get((notification.id, notification.recipient_user_id))
            if recipient is None:
                if self._mark_failed(
                    notification,
                    now=now,
                    retryable=False,
                    code=NotificationFailureCode.RECIPIENT_INELIGIBLE,
                ):
                    permanent_failed += 1
                else:
                    stale_results += 1
                continue
            if notification.id not in applicable_ids:
                if self._mark_failed(
                    notification,
                    now=now,
                    retryable=False,
                    code=NotificationFailureCode.EVENT_NO_LONGER_APPLICABLE,
                ):
                    permanent_failed += 1
                else:
                    stale_results += 1
                continue
            try:
                self.sender.send(self._render(notification.event, recipient.email))
            except NotificationDeliveryError as error:
                retryable = error.retryable and notification.attempt_count < MAX_DELIVERY_ATTEMPTS
                if self._mark_failed(notification, now=now, retryable=retryable, code=error.code):
                    if retryable:
                        retryable_failed += 1
                    else:
                        permanent_failed += 1
                else:
                    stale_results += 1
                continue
            if self._mark_delivered(notification, now):
                delivered += 1
            else:
                stale_results += 1
        return DispatchResult(
            claimed=len(claimed),
            delivered=delivered,
            retryable_failed=retryable_failed,
            permanent_failed=permanent_failed,
            stale_results=stale_results,
        )

    @staticmethod
    def _snapshot(row: NotificationOutbox) -> ClaimedNotification:
        if row.claim_token is None:
            raise RuntimeError("Claimed notification has no authoritative token")
        try:
            event = MarketplaceNotificationEvent(row.event_type)
        except ValueError:
            event = None
        return ClaimedNotification(
            id=row.id,
            claim_token=row.claim_token,
            event=event,
            recipient_user_id=row.recipient_user_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            attempt_count=row.attempt_count,
        )

    def _resolve_recipients(
        self, notifications: list[ClaimedNotification]
    ) -> dict[tuple[UUID, UUID], RecipientContext]:
        if not notifications:
            return {}
        user_ids = {item.recipient_user_id for item in notifications}
        users = {
            user.id: RecipientContext(user_id=user.id, email=user.email)
            for user in self.session.scalars(
                select(User).where(
                    User.id.in_(user_ids),
                    User.status == UserStatus.ACTIVE,
                    User.email_verified_at.is_not(None),
                )
            )
        }
        authorized: set[tuple[UUID, UUID]] = set()
        offer_items = [
            item
            for item in notifications
            if item.event is MarketplaceNotificationEvent.OFFER_AVAILABLE
            and item.resource_type == "OFFER"
        ]
        customer_booking_items = [
            item
            for item in notifications
            if item.event
            in {
                MarketplaceNotificationEvent.BOOKING_CONFIRMED,
                MarketplaceNotificationEvent.BOOKING_REJECTED,
            }
            and item.resource_type == "BOOKING"
        ]
        operator_booking_items = [
            item
            for item in notifications
            if item.event is MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION
            and item.resource_type == "BOOKING"
        ]
        authorized.update(self._authorized_offer_pairs(offer_items))
        authorized.update(self._authorized_customer_booking_pairs(customer_booking_items))
        authorized.update(self._authorized_operator_booking_pairs(operator_booking_items))
        return {
            (item.id, item.recipient_user_id): users[item.recipient_user_id]
            for item in notifications
            if (item.resource_id, item.recipient_user_id) in authorized
            and item.recipient_user_id in users
        }

    def _applicable_notification_ids(
        self, notifications: list[ClaimedNotification], *, now: datetime
    ) -> set[UUID]:
        """Return notifications whose current canonical lifecycle still matches their copy."""
        offer_items = [
            item
            for item in notifications
            if item.event is MarketplaceNotificationEvent.OFFER_AVAILABLE
            and item.resource_type == "OFFER"
        ]
        booking_items = [
            item
            for item in notifications
            if item.event
            in {
                MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION,
                MarketplaceNotificationEvent.BOOKING_CONFIRMED,
                MarketplaceNotificationEvent.BOOKING_REJECTED,
            }
            and item.resource_type == "BOOKING"
        ]
        applicable: set[UUID] = set()
        if offer_items:
            offers = {
                offer.id: offer
                for offer in self.session.scalars(
                    select(OperatorOffer).where(
                        OperatorOffer.id.in_([item.resource_id for item in offer_items])
                    )
                )
            }
            applicable.update(
                item.id
                for item in offer_items
                if (offer := offers.get(item.resource_id)) is not None
                and effective_offer_status(offer.status, offer.valid_until, now=now)
                is EffectiveOfferStatus.SUBMITTED
            )
        if booking_items:
            statuses = dict(
                self.session.execute(
                    select(Booking.id, Booking.status).where(
                        Booking.id.in_([item.resource_id for item in booking_items])
                    )
                )
                .tuples()
                .all()
            )
            required_status = {
                MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION: (
                    BookingStatus.PENDING_OPERATOR_CONFIRMATION
                ),
                MarketplaceNotificationEvent.BOOKING_CONFIRMED: BookingStatus.CONFIRMED,
                MarketplaceNotificationEvent.BOOKING_REJECTED: BookingStatus.REJECTED,
            }
            applicable.update(
                item.id
                for item in booking_items
                if item.event is not None
                and statuses.get(item.resource_id) is required_status[item.event]
            )
        return applicable

    def _authorized_offer_pairs(self, items: list[ClaimedNotification]) -> set[tuple[UUID, UUID]]:
        if not items:
            return set()
        return set(
            self.session.execute(
                select(OperatorOffer.id, OrganizationMembership.user_id)
                .join(TripRequest, TripRequest.id == OperatorOffer.trip_request_id)
                .join(Organization, Organization.customer_id == TripRequest.customer_id)
                .join(
                    OrganizationMembership,
                    OrganizationMembership.organization_id == Organization.id,
                )
                .where(
                    OperatorOffer.id.in_([item.resource_id for item in items]),
                    Organization.organization_type == OrganizationType.CUSTOMER,
                    OrganizationMembership.user_id.in_([item.recipient_user_id for item in items]),
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                    OrganizationMembership.role.in_(_CUSTOMER_ROLES),
                )
            )
            .tuples()
            .all()
        )

    def _authorized_customer_booking_pairs(
        self, items: list[ClaimedNotification]
    ) -> set[tuple[UUID, UUID]]:
        if not items:
            return set()
        return set(
            self.session.execute(
                select(Booking.id, OrganizationMembership.user_id)
                .join(TripRequest, TripRequest.id == Booking.trip_request_id)
                .join(Organization, Organization.customer_id == TripRequest.customer_id)
                .join(
                    OrganizationMembership,
                    OrganizationMembership.organization_id == Organization.id,
                )
                .where(
                    Booking.id.in_([item.resource_id for item in items]),
                    Organization.organization_type == OrganizationType.CUSTOMER,
                    OrganizationMembership.user_id.in_([item.recipient_user_id for item in items]),
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                    OrganizationMembership.role.in_(_CUSTOMER_ROLES),
                )
            )
            .tuples()
            .all()
        )

    def _authorized_operator_booking_pairs(
        self, items: list[ClaimedNotification]
    ) -> set[tuple[UUID, UUID]]:
        if not items:
            return set()
        return set(
            self.session.execute(
                select(Booking.id, OrganizationMembership.user_id)
                .join(Organization, Organization.operator_id == Booking.operator_id)
                .join(
                    OrganizationMembership,
                    OrganizationMembership.organization_id == Organization.id,
                )
                .where(
                    Booking.id.in_([item.resource_id for item in items]),
                    Organization.organization_type == OrganizationType.OPERATOR,
                    OrganizationMembership.user_id.in_([item.recipient_user_id for item in items]),
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                    OrganizationMembership.role.in_(_OPERATOR_DECIDER_ROLES),
                )
            )
            .tuples()
            .all()
        )

    def _render(self, event: MarketplaceNotificationEvent, recipient: str) -> MarketplaceEmail:
        templates = {
            MarketplaceNotificationEvent.OFFER_AVAILABLE: (
                "A new Sky Bridge Jet offer is available",
                "A new offer is available for your trip request. Open Sky Bridge Jet to review it.",
                "/portal/trip-requests",
            ),
            MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION: (
                "A booking requires operator review",
                "A booking is awaiting operator confirmation. Open Sky Bridge Jet to review it.",
                "/operator/bookings",
            ),
            MarketplaceNotificationEvent.BOOKING_CONFIRMED: (
                "Your Sky Bridge Jet booking is confirmed",
                "Your booking has been confirmed. Open Sky Bridge Jet for current details.",
                "/portal/bookings",
            ),
            MarketplaceNotificationEvent.BOOKING_REJECTED: (
                "Your Sky Bridge Jet booking was not confirmed",
                "Your booking was not confirmed by the operator. "
                "Open Sky Bridge Jet for the current booking status.",
                "/portal/bookings",
            ),
        }
        subject, body, route = templates[event]
        return MarketplaceEmail(
            recipient=recipient,
            subject=subject,
            text_body=f"{body}\n\n{self.settings.web_public_origin}{route}",
        )

    def _mark_delivered(self, notification: ClaimedNotification, now: datetime) -> bool:
        from sky_bridge_jet.modules.notifications.domain import NotificationClaimConflictError

        try:
            with self.session.begin():
                NotificationOutboxService(self.session).mark_delivered(
                    notification.id, notification.claim_token, now=now
                )
        except NotificationClaimConflictError:
            return False
        return True

    def _mark_failed(
        self,
        notification: ClaimedNotification,
        *,
        now: datetime,
        retryable: bool,
        code: NotificationFailureCode,
    ) -> bool:
        from sky_bridge_jet.modules.notifications.domain import NotificationClaimConflictError

        next_attempt_at = None
        if retryable:
            next_attempt_at = now + RETRY_DELAYS[notification.attempt_count - 1]
        try:
            with self.session.begin():
                NotificationOutboxService(self.session).mark_delivery_failed(
                    notification.id,
                    notification.claim_token,
                    now=now,
                    retryable=retryable,
                    failure_code=code.value,
                    next_attempt_at=next_attempt_at,
                )
        except NotificationClaimConflictError:
            return False
        return True
