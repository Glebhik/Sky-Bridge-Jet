"""Small production dispatcher process; no HTTP send/retry authority."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from datetime import UTC, datetime

from sky_bridge_jet.core.config import get_settings
from sky_bridge_jet.core.logging import configure_logging
from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.notifications.delivery import build_marketplace_notification_sender
from sky_bridge_jet.modules.notifications.marketplace import MarketplaceNotificationDispatcher

logger = logging.getLogger(__name__)


def dispatch_once() -> int:
    settings = get_settings()
    if not settings.marketplace_email_enabled:
        logger.info("notification_dispatch_disabled")
        return 0
    sender = build_marketplace_notification_sender(settings)
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender, settings).dispatch_batch(
            now=datetime.now(UTC), limit=settings.marketplace_dispatch_batch_size
        )
    logger.info(
        "notification_dispatch_completed",
        extra={
            "claimed": result.claimed,
            "accepted": result.delivered,
            "retryable_failed": result.retryable_failed,
            "permanent_failed": result.permanent_failed,
            "stale_results": result.stale_results,
        },
    )
    return result.claimed


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch bounded marketplace notification work")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    while not stopped.is_set():
        dispatch_once()
        if args.once:
            return
        stopped.wait(settings.marketplace_dispatch_poll_seconds)


if __name__ == "__main__":
    main()
