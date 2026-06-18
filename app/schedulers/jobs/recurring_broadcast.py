"""Background jobs for scheduled + recurring user broadcasts.

- ``dispatch_recurring_broadcasts_job``: an APScheduler recurring job (runs every
  minute) that fires due recurring rules. Each fire creates a NEW broadcast run
  (history is append-only) and advances the rule's next_run_at.
- ``reconcile_scheduled_broadcasts``: re-arms one-off jobs for broadcasts left in
  'scheduled' after a restart (past-due ones run immediately).
"""
from datetime import datetime, timedelta

import pytz

from app.cache.client import redis_client
from app.cache.keys import CacheKey
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.repositories.user_broadcast import (
    BroadcastRecurringRuleRepository,
    UserBroadcastRepository,
)
from app.services.recurrence import compute_next_run

logger = get_logger(__name__)
TZ = pytz.timezone(settings.TIMEZONE)
LOCK_TTL = 120


def _enqueue_send(broadcast_id: str) -> None:
    """Schedule the delivery of a broadcast as a one-off job on the running
    scheduler (non-blocking)."""
    from app.schedulers.jobs.user_broadcast import run_user_broadcast_job
    from app.schedulers.setup import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:  # pragma: no cover - scheduler always set in app runtime
        logger.error("scheduler_unavailable", broadcast_id=broadcast_id)
        return
    scheduler.add_job(
        run_user_broadcast_job,
        "date",
        args=[broadcast_id],
        id=f"user_broadcast:{broadcast_id}",
        replace_existing=True,
        misfire_grace_time=3600,
    )


async def dispatch_recurring_broadcasts_job() -> None:
    """Fire every due recurring rule. Idempotent per minute via a short lock."""
    lock_key = CacheKey.recurring_broadcast_lock()
    if not await redis_client.set_nx(lock_key, "1", ttl=LOCK_TTL):
        return

    try:
        from app.bot.client import get_bot
        from app.services.user_broadcast import UserBroadcastService

        now = datetime.now(TZ)
        async with AsyncSessionFactory() as session:
            rule_repo = BroadcastRecurringRuleRepository(session)
            bcast_repo = UserBroadcastRepository(session)
            svc = UserBroadcastService(session, get_bot())

            due = await rule_repo.get_due(now)
            for rule in due:
                source = await bcast_repo.get_by_id(rule.broadcast_id)
                if source is None:
                    await rule_repo.set_active(rule.id, False)
                    await session.commit()
                    continue

                run = await svc.create_recurring_run(source)  # commits
                _enqueue_send(str(run.id))

                # Preserve the configured time-of-day: it is encoded in the
                # current next_run_at, so re-derive it (in local TZ) and pin the
                # next fire to the same hour:minute regardless of when the
                # dispatcher actually ran this minute.
                anchor = rule.next_run_at.astimezone(TZ)
                next_run = compute_next_run(
                    frequency=rule.frequency,
                    interval=rule.interval,
                    day_of_week=rule.day_of_week,
                    day_of_month=rule.day_of_month,
                    after=now,
                    hour=anchor.hour,
                    minute=anchor.minute,
                )
                await rule_repo.set_next_run(rule.id, next_run)
                await session.commit()
                logger.info(
                    "recurring_rule_fired",
                    rule_id=str(rule.id),
                    run_id=str(run.id),
                    next_run_at=str(next_run),
                )
    except Exception as exc:
        logger.error("recurring_dispatch_failed", error=str(exc))
    finally:
        await redis_client.delete(lock_key)


async def reconcile_scheduled_broadcasts() -> None:
    """On startup, re-arm one-off jobs for broadcasts still 'scheduled'.

    Past-due ones (missed during downtime) are scheduled to run shortly."""
    try:
        now = datetime.now(TZ)
        async with AsyncSessionFactory() as session:
            repo = UserBroadcastRepository(session)
            scheduled = await repo.list_scheduled()
        for b in scheduled:
            run_at = b.scheduled_for
            if run_at is None or run_at <= now:
                run_at = now + timedelta(seconds=10)
            from app.schedulers.setup import get_scheduler
            from app.schedulers.jobs.user_broadcast import run_user_broadcast_job

            scheduler = get_scheduler()
            if scheduler is not None:
                scheduler.add_job(
                    run_user_broadcast_job,
                    "date",
                    run_date=run_at,
                    args=[str(b.id)],
                    id=f"user_broadcast:{b.id}",
                    replace_existing=True,
                    misfire_grace_time=3600,
                )
        if scheduled:
            logger.info("scheduled_broadcasts_reconciled", count=len(scheduled))
    except Exception as exc:
        logger.error("scheduled_reconcile_failed", error=str(exc))
