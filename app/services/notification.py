from datetime import datetime, timedelta

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.notification_log import DeliveryStatus, ReminderType
from app.db.models.reservation import Reservation
from app.repositories.notification import NotificationRepository

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)


class NotificationService:
    """Low-level Telegram message sender with error isolation."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, telegram_id: int, text: str) -> tuple[bool, str | None]:
        """Send a message. Returns (success, error_message)."""
        try:
            await self._bot.send_message(telegram_id, text, parse_mode="HTML")
            return True, None
        except TelegramAPIError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"unexpected: {exc}"


class ReminderService:
    """Orchestrates reminder queries and delivery, logging every outcome."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._notif_repo = NotificationRepository(session)
        self._notif_svc = NotificationService(bot)

    async def send_same_day_reminders(self) -> int:
        """Send 12 PM same-day reminders. Returns count of successfully delivered messages."""
        today = datetime.now(TZ).date()
        reservations = await self._notif_repo.get_reservations_for_same_day_reminder(today)

        sent = 0
        for reservation in reservations:
            ok = await self._deliver_same_day(reservation)
            if ok:
                sent += 1

        return sent

    async def send_pre_session_reminders(self) -> int:
        """Send 30-minute-before reminders. Checks a ±5-minute window around the
        30-minute mark to tolerate scheduler jitter. Returns delivered count."""
        now = datetime.now(TZ)
        from_dt = now + timedelta(minutes=25)
        to_dt = now + timedelta(minutes=35)

        reservations = await self._notif_repo.get_reservations_for_pre_session_reminder(
            from_dt, to_dt
        )

        sent = 0
        for reservation in reservations:
            ok = await self._deliver_pre_session(reservation)
            if ok:
                sent += 1

        return sent

    async def _deliver_same_day(self, reservation: Reservation) -> bool:
        user = reservation.user
        slot = reservation.slot
        channel = slot.channel

        slot_local = slot.slot_datetime.astimezone(TZ)
        hour = slot_local.hour
        minute = slot_local.minute
        period = "AM" if hour < 12 else "PM"
        display_hour = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
        time_str = f"{display_hour}:{minute:02d} {period}"

        text = (
            f"⏰ <b>Live Session Reminder</b>\n\n"
            f"You have a live session today at <b>{time_str}</b>.\n\n"
            f"📺 Channel:\n{channel.name}\n"
        )
        if channel.invite_link:
            text += f"\n🔗 Join Channel:\n{channel.invite_link}\n"
        text += "\nGood luck with your presentation ✨"

        return await self._log_and_send(reservation, ReminderType.SAME_DAY, user.telegram_id, text)

    async def _deliver_pre_session(self, reservation: Reservation) -> bool:
        user = reservation.user
        slot = reservation.slot
        channel = slot.channel

        text = (
            f"🚀 <b>Your live session starts in 30 minutes.</b>\n\n"
            f"📺 Channel:\n{channel.name}\n"
        )
        if channel.invite_link:
            text += f"\n🔗 Join Here:\n{channel.invite_link}\n"
        text += "\nSee you soon ✨"

        return await self._log_and_send(reservation, ReminderType.PRE_SESSION, user.telegram_id, text)

    async def _log_and_send(
        self,
        reservation: Reservation,
        reminder_type: ReminderType,
        telegram_id: int,
        text: str,
    ) -> bool:
        success, error = await self._notif_svc.send(telegram_id, text)
        status = DeliveryStatus.SENT if success else DeliveryStatus.FAILED

        await self._notif_repo.log(
            reservation_id=reservation.id,
            reminder_type=reminder_type,
            status=status,
            error_message=error,
        )

        if success:
            logger.info(
                "reminder_sent",
                reminder_type=reminder_type.value,
                reservation_id=str(reservation.id),
                telegram_id=telegram_id,
            )
        else:
            logger.warning(
                "reminder_failed",
                reminder_type=reminder_type.value,
                reservation_id=str(reservation.id),
                telegram_id=telegram_id,
                error=error,
            )

        return success
