"""Inactivity reservation reminder.

Users whose last reservation predates INACTIVITY_REMINDER_THRESHOLD_DAYS get a
DM nudging them to come back. The cycle repeats every threshold period until
the user books again — booking resets `users.last_reservation_at`, which is
the eligibility query's anchor (see `ReservationService._perform_booking`).

Sends via `bot.send_message` directly rather than `NotificationService.send`
because `TelegramForbiddenError` is a `TelegramAPIError` subclass —
`NotificationService.send`'s broad `except TelegramAPIError` swallows it
before a caller could branch on it, so blocked-user detection would silently
never fire. `UserBroadcastService` has the same requirement and uses the same
direct-call + ordered-except pattern for the same reason.
"""
import asyncio
import uuid
from datetime import datetime

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories.user import UserRepository

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)

# Kept as a single top-level constant so the copy can be changed without
# touching delivery logic.
INACTIVITY_REMINDER_MESSAGE = (
    "Hello 🌹\n\n"
    "We have missed seeing you in the \"19 Steps Toward Peace\" program.\n\n"
    "We would be delighted to have you join us again whenever you have the "
    "opportunity.\n\n"
    "We look forward to welcoming you back soon."
)

# Candidates are loaded id+telegram_id only, one page at a time, so a large
# users table is never hydrated into memory at once.
_BATCH_SIZE = 200


class InactivityReminderService:
    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._bot = bot
        self._user_repo = UserRepository(session)

    async def send_due_reminders(self) -> dict[str, int]:
        """Scan for eligible users, page by page, and deliver a reminder DM to
        each. Returns per-run counters for the caller to log."""
        counts = {"scanned": 0, "sent": 0, "failed": 0, "blocked": 0}
        if not settings.INACTIVITY_REMINDER_ENABLED:
            return counts

        now = datetime.now(TZ)
        threshold_days = settings.INACTIVITY_REMINDER_THRESHOLD_DAYS
        # Reuse the broadcast throttle so a large scan never floods Telegram.
        rate = max(settings.USER_BROADCAST_RATE_LIMIT, 1)
        interval = 1.0 / rate

        after_id: uuid.UUID | None = None
        while True:
            batch = await self._user_repo.get_inactivity_reminder_candidates(
                now=now, threshold_days=threshold_days, after_id=after_id, limit=_BATCH_SIZE
            )
            if not batch:
                break

            for user_id, telegram_id in batch:
                counts["scanned"] += 1
                outcome = await self._remind_one(user_id, telegram_id)
                counts[outcome] += 1
                await asyncio.sleep(interval)

            after_id = batch[-1][0]
            if len(batch) < _BATCH_SIZE:
                break

        return counts

    async def _remind_one(self, user_id: uuid.UUID, telegram_id: int) -> str:
        """Send one reminder. Returns 'sent' | 'failed' | 'blocked'."""
        try:
            await self._bot.send_message(
                telegram_id, INACTIVITY_REMINDER_MESSAGE, parse_mode="HTML"
            )
        except TelegramForbiddenError as exc:
            await self._user_repo.mark_bot_blocked(user_id)
            await self._session.commit()
            logger.info(
                "inactivity_reminder_blocked", user_id=str(user_id), error=str(exc)
            )
            return "blocked"
        except TelegramAPIError as exc:
            logger.warning(
                "inactivity_reminder_failed", user_id=str(user_id), error=str(exc)
            )
            return "failed"
        except Exception as exc:  # never let one recipient kill the scan
            logger.warning(
                "inactivity_reminder_unexpected_error",
                user_id=str(user_id),
                error=str(exc),
            )
            return "failed"

        await self._user_repo.mark_inactivity_reminder_sent(user_id, datetime.now(TZ))
        await self._session.commit()
        logger.info("inactivity_reminder_sent", user_id=str(user_id))
        return "sent"
