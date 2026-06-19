"""Reservation cancellation notification delivery.

Runs OUT-OF-BAND from the cancellation transaction (in its own session, via a
delayed one-off scheduler job) so a slow or failing Telegram send can never
block or roll back the cancellation. Users who have blocked the bot are skipped.
"""
import html
import uuid

import pytz
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.reservation import Reservation
from app.repositories.reservation import ReservationRepository
from app.services.notification import NotificationService

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)


class ReservationNotificationService:
    """Delivers a single reservation-cancellation DM, given a reservation id."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._res_repo = ReservationRepository(session)
        self._notif = NotificationService(bot)

    async def deliver_cancellation(
        self, reservation_id: uuid.UUID, reason: str | None = None
    ) -> None:
        """Load the reservation + user and send the cancellation DM.

        Never raises for a delivery failure; the cancellation has already
        committed. Skips users flagged as having blocked the bot.
        """
        reservation = await self._res_repo.get_reservation_with_details(reservation_id)
        if reservation is None:
            logger.warning(
                "reservation_cancel_notify_missing", reservation_id=str(reservation_id)
            )
            return

        user = reservation.user
        if user is None or user.bot_blocked:
            return

        text = self._format(reservation, reason)
        success, error = await self._notif.send(user.telegram_id, text)

        if success:
            logger.info(
                "reservation_cancel_notify_sent",
                reservation_id=str(reservation_id),
                user_id=str(user.id),
            )
        else:
            logger.warning(
                "reservation_cancel_notify_failed",
                reservation_id=str(reservation_id),
                user_id=str(user.id),
                error=error,
            )

    @staticmethod
    def _format(reservation: Reservation, reason: str | None) -> str:
        """HTML-safe cancellation message including the cancelled slot's details."""
        slot_local = reservation.slot.slot_datetime.astimezone(TZ)
        channel_name = html.escape(reservation.channel.name)

        text = (
            "❌ <b>Reservation Cancelled</b>\n\n"
            "Your reservation has been cancelled by the support team.\n\n"
            f"📅 Date: <b>{slot_local.strftime('%A, %d %B %Y')}</b>\n"
            f"🕐 Time: <b>{slot_local.strftime('%I:%M %p')}</b>\n"
            f"📡 Channel: {channel_name}"
        )
        clean_reason = (reason or "").strip()
        if clean_reason:
            text += f"\n\nReason: {html.escape(clean_reason)}"
        return text
