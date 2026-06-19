"""One-off delivery of admin reservation-cancellation notifications.

`enqueue_reservation_cancellation_notification` is called from the admin cancel
flow. It schedules a short-delayed "date" job so the enclosing DB transaction is
guaranteed committed before `run_reservation_cancellation_notification_job` reads
the row in its own session. A failed or slow send can never roll back the
cancellation.

Mirrors the score-notification delivery pattern (app/schedulers/jobs/score_notification.py).
"""
import uuid
from datetime import datetime, timedelta

import pytz

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.services.reservation_notification import ReservationNotificationService

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)

# Reuse the score-notification settle delay: the same "wait for the request's
# commit to land" reasoning applies. Floor at 1s so the job never races the commit.
_COMMIT_SETTLE_DELAY_SECONDS = max(settings.SCORE_NOTIFY_DELAY_SECONDS, 1)


def enqueue_reservation_cancellation_notification(
    reservation_id: uuid.UUID, reason: str | None = None
) -> None:
    """Schedule a cancellation DM. Call AFTER the cancellation row is mutated.

    Never raises — a scheduling hiccup must not break the cancellation flow.
    """
    # Imported lazily: app.schedulers.setup transitively imports the reservation
    # service, which imports this module — a top-level import would deadlock.
    from app.schedulers.setup import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        logger.warning(
            "reservation_cancel_notify_no_scheduler", reservation_id=str(reservation_id)
        )
        return

    run_date = datetime.now(TZ) + timedelta(seconds=_COMMIT_SETTLE_DELAY_SECONDS)
    try:
        scheduler.add_job(
            run_reservation_cancellation_notification_job,
            "date",
            run_date=run_date,
            args=[str(reservation_id), reason],
            id=f"reservation_cancel_notify:{reservation_id}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception as exc:  # scheduling must never break the caller
        logger.warning(
            "reservation_cancel_notify_enqueue_failed",
            reservation_id=str(reservation_id),
            error=str(exc),
        )


async def run_reservation_cancellation_notification_job(
    reservation_id: str, reason: str | None = None
) -> None:
    """APScheduler one-off job: deliver one reservation-cancellation notification."""
    from app.bot.client import get_bot

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = ReservationNotificationService(session, bot)
            await svc.deliver_cancellation(uuid.UUID(reservation_id), reason)
    except Exception as exc:
        logger.error(
            "reservation_cancellation_notification_job_failed",
            reservation_id=reservation_id,
            error=str(exc),
        )
