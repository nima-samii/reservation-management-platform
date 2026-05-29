from datetime import datetime

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.channel import Channel
from app.repositories.broadcast import BroadcastRepository, ScheduleEventRepository
from app.repositories.channel import ChannelRepository
from app.repositories.reservation import ReservationRepository
from app.services.schedule_formatter import ScheduleFormatter

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)


class BroadcastService:
    """Orchestrates the daily schedule broadcast to each active channel.

    Responsibilities:
    - Query reservations and events per channel
    - Render the schedule message via ScheduleFormatter
    - Send to Telegram, pin the new message, unpin the previous one
    - Log every outcome in broadcast_logs for auditing and future retries
    """

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._bot = bot
        self._channel_repo = ChannelRepository(session)
        self._res_repo = ReservationRepository(session)
        self._broadcast_repo = BroadcastRepository(session)
        self._event_repo = ScheduleEventRepository(session)
        self._formatter = ScheduleFormatter()

    async def run_daily_broadcast(self) -> dict[str, str]:
        """Broadcast today's schedule to every active channel.

        Returns a dict mapping channel name → outcome ("sent" | "skipped" | "failed").
        """
        today = datetime.now(TZ).date()
        channels = await self._channel_repo.get_active_channels_ordered()
        results: dict[str, str] = {}

        for channel in channels:
            outcome = await self._broadcast_channel(channel, today)
            results[channel.name] = outcome
            logger.info(
                "broadcast_channel_done",
                channel=channel.name,
                outcome=outcome,
                date=str(today),
            )

        return results

    async def _broadcast_channel(self, channel: Channel, today) -> str:
        existing = await self._broadcast_repo.get_for_channel_and_date(channel.id, today)
        if existing and existing.status == "sent":
            logger.debug("broadcast_skipped_duplicate", channel=channel.name)
            return "skipped"

        reservations = await self._res_repo.get_active_reservations_for_date_and_channel(
            channel.id, today
        )
        events = await self._event_repo.get_for_date_and_channel(channel.id, today)

        text = self._formatter.render(channel, today, reservations, events)

        try:
            msg = await self._bot.send_message(
                chat_id=channel.telegram_channel_id,
                text=text,
                parse_mode="HTML",
            )
        except TelegramAPIError as exc:
            logger.error(
                "broadcast_send_failed",
                channel=channel.name,
                error=str(exc),
            )
            await self._broadcast_repo.log_failure(channel.id, today, str(exc))
            return "failed"

        await self._broadcast_repo.log_success(channel.id, msg.message_id, today)

        await self._pin_and_cleanup(channel, msg.message_id, today)

        logger.info(
            "broadcast_sent",
            channel=channel.name,
            message_id=msg.message_id,
            reservations=len(reservations),
        )
        return "sent"

    async def _pin_and_cleanup(self, channel: Channel, new_msg_id: int, today) -> None:
        previous = await self._broadcast_repo.get_previous_sent(channel.id, today)

        if previous and previous.telegram_message_id:
            try:
                await self._bot.unpin_chat_message(
                    chat_id=channel.telegram_channel_id,
                    message_id=previous.telegram_message_id,
                )
                if settings.DELETE_PREVIOUS_BROADCAST:
                    await self._bot.delete_message(
                        chat_id=channel.telegram_channel_id,
                        message_id=previous.telegram_message_id,
                    )
            except TelegramAPIError as exc:
                logger.warning(
                    "broadcast_unpin_failed",
                    channel=channel.name,
                    old_msg_id=previous.telegram_message_id,
                    error=str(exc),
                )

        if settings.ENABLE_BROADCAST_AUTO_PIN:
            try:
                await self._bot.pin_chat_message(
                    chat_id=channel.telegram_channel_id,
                    message_id=new_msg_id,
                    disable_notification=True,
                )
            except TelegramAPIError as exc:
                logger.warning(
                    "broadcast_pin_failed",
                    channel=channel.name,
                    message_id=new_msg_id,
                    error=str(exc),
                )
