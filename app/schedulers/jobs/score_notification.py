"""One-off delivery of score-change notifications.

`enqueue_score_notification` is called from each score-mutation flow. It schedules
a short-delayed "date" job so the enclosing DB transaction is guaranteed committed
before `run_score_notification_job` reads the row in its own session.
"""
import uuid
from datetime import datetime, timedelta

import pytz

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.score import ScoreTransactionType
from app.db.session import AsyncSessionFactory
from app.services.score_notification import ScoreNotificationService

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)


def _should_notify(transaction_type: str) -> bool:
    """Per-type opt-in. Reservation reward/cancellation are high-churn and off by default."""
    if not settings.SCORE_CHANGE_NOTIFICATIONS_ENABLED:
        return False
    if transaction_type == ScoreTransactionType.RESERVATION_REWARD.value:
        return settings.NOTIFY_ON_REWARD
    if transaction_type == ScoreTransactionType.RESERVATION_CANCELLATION.value:
        return settings.NOTIFY_ON_CANCEL_ROLLBACK
    return True


def enqueue_score_notification(transaction_id: uuid.UUID, transaction_type: str) -> None:
    """Schedule a score-change DM. Call AFTER the score transaction is committed.

    Filtered by feature flags up front so disabled/opt-out types never spawn a job.
    Never raises — a scheduling hiccup must not break the score mutation flow.
    """
    if not _should_notify(transaction_type):
        return

    # Imported lazily: app.schedulers.setup transitively imports the reservation
    # service, which imports this module — a top-level import would deadlock.
    from app.schedulers.setup import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        logger.warning("score_notify_no_scheduler", transaction_id=str(transaction_id))
        return

    run_date = datetime.now(TZ) + timedelta(seconds=max(settings.SCORE_NOTIFY_DELAY_SECONDS, 1))
    try:
        scheduler.add_job(
            run_score_notification_job,
            "date",
            run_date=run_date,
            args=[str(transaction_id)],
            id=f"score_notify:{transaction_id}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception as exc:  # scheduling must never break the caller
        logger.warning(
            "score_notify_enqueue_failed",
            transaction_id=str(transaction_id),
            error=str(exc),
        )


async def run_score_notification_job(transaction_id: str) -> None:
    """APScheduler one-off job: deliver one score-change notification."""
    from app.bot.client import get_bot

    try:
        bot = get_bot()
        async with AsyncSessionFactory() as session:
            svc = ScoreNotificationService(session, bot)
            await svc.deliver(uuid.UUID(transaction_id))
    except Exception as exc:
        logger.error(
            "score_notification_job_failed",
            transaction_id=transaction_id,
            error=str(exc),
        )
