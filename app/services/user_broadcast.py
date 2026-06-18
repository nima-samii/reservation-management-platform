"""User-broadcast orchestration: create a broadcast, snapshot its audience, and
deliver to every recipient in the background with throttling, per-recipient
delivery tracking, and blocked-bot detection.

Reuses the shared AudienceResolver so audience filtering is never duplicated,
and the project's single Bot instance for sending.
"""
import asyncio
import uuid

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user_broadcast import UserBroadcast, UserBroadcastStatus
from app.repositories.user import UserRepository
from app.repositories.user_broadcast import (
    UserBroadcastRecipientRepository,
    UserBroadcastRepository,
)
from app.services.segmentation import SegmentFilter, SegmentationService

logger = get_logger(__name__)


class UserBroadcastService:
    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._bot = bot
        self._segmentation = SegmentationService(session)
        self._broadcast_repo = UserBroadcastRepository(session)
        self._recipient_repo = UserBroadcastRecipientRepository(session)
        self._user_repo = UserRepository(session)

    # ── Creation (request path — fast, never sends) ─────────────────────────

    async def create_broadcast(
        self,
        *,
        message: str,
        parse_mode: str,
        audience_type: str,
        segment_filter: SegmentFilter,
        filters_payload: dict | None = None,
        created_by: str,
    ) -> UserBroadcast:
        """Create the broadcast row and snapshot its recipient set.

        ``audience_type`` is the display label ("custom" for advanced segments);
        ``segment_filter`` is the resolved filter used to select recipients;
        ``filters_payload`` is the JSON persisted for analytics/future reuse
        (NULL for quick segments). Does NOT send — that happens in
        run_broadcast() on a background worker.
        """
        recipients = await self._segmentation.fetch_recipients(segment_filter)

        broadcast = await self._broadcast_repo.create(
            message=message,
            parse_mode=parse_mode,
            audience_type=audience_type,
            filters=filters_payload,
            created_by=created_by,
            total_recipients=len(recipients),
        )
        await self._recipient_repo.bulk_create(broadcast.id, recipients)
        await self._session.commit()

        logger.info(
            "user_broadcast_created",
            broadcast_id=str(broadcast.id),
            audience=audience_type,
            recipients=len(recipients),
            created_by=created_by,
        )
        return broadcast

    # ── Delivery (background path) ──────────────────────────────────────────

    async def run_broadcast(self, broadcast_id: uuid.UUID) -> None:
        """Deliver a pending broadcast. Idempotent-ish: only sends rows still
        in PENDING, so a re-run after a crash resumes rather than duplicates."""
        broadcast = await self._broadcast_repo.get_by_id(broadcast_id)
        if broadcast is None:
            logger.warning("user_broadcast_missing", broadcast_id=str(broadcast_id))
            return
        if broadcast.status not in (
            UserBroadcastStatus.PENDING.value,
            UserBroadcastStatus.PROCESSING.value,
        ):
            logger.info(
                "user_broadcast_not_runnable",
                broadcast_id=str(broadcast_id),
                status=broadcast.status,
            )
            return

        await self._broadcast_repo.mark_processing(broadcast_id)
        await self._session.commit()

        parse_mode = None if broadcast.parse_mode == "plain" else broadcast.parse_mode
        rate = max(settings.USER_BROADCAST_RATE_LIMIT, 1)
        interval = 1.0 / rate
        persist_every = rate  # roughly once per second

        # Counters seed from any already-recorded results (crash resume).
        success = broadcast.success_count
        failed = broadcast.failed_count
        blocked = broadcast.blocked_count

        try:
            pending = await self._recipient_repo.get_pending(broadcast_id)
            for i, recipient in enumerate(pending, start=1):
                try:
                    await self._bot.send_message(
                        chat_id=recipient.telegram_id,
                        text=broadcast.message,
                        parse_mode=parse_mode,
                    )
                    await self._recipient_repo.mark_sent(recipient.id)
                    success += 1
                except TelegramForbiddenError as exc:
                    # User blocked the bot — flag them and persist immediately.
                    await self._recipient_repo.mark_blocked(recipient.id, str(exc))
                    await self._user_repo.mark_bot_blocked(recipient.user_id)
                    await self._session.commit()
                    blocked += 1
                except TelegramAPIError as exc:
                    await self._recipient_repo.mark_failed(recipient.id, str(exc))
                    failed += 1
                except Exception as exc:  # never let one recipient kill the run
                    await self._recipient_repo.mark_failed(recipient.id, str(exc))
                    failed += 1
                    logger.warning(
                        "user_broadcast_unexpected_error",
                        broadcast_id=str(broadcast_id),
                        error=str(exc),
                    )

                # Persist progress periodically so the progress endpoint is live.
                if i % persist_every == 0:
                    await self._broadcast_repo.update_counts(
                        broadcast_id,
                        success_count=success,
                        failed_count=failed,
                        blocked_count=blocked,
                    )
                    await self._session.commit()

                await asyncio.sleep(interval)

            await self._broadcast_repo.mark_finished(
                broadcast_id,
                status=UserBroadcastStatus.COMPLETED,
                success_count=success,
                failed_count=failed,
                blocked_count=blocked,
            )
            await self._session.commit()
            logger.info(
                "user_broadcast_completed",
                broadcast_id=str(broadcast_id),
                success=success,
                failed=failed,
                blocked=blocked,
            )
        except Exception as exc:
            # Infrastructure-level failure (DB, etc.) — mark the whole run failed.
            await self._session.rollback()
            await self._broadcast_repo.mark_finished(
                broadcast_id,
                status=UserBroadcastStatus.FAILED,
                success_count=success,
                failed_count=failed,
                blocked_count=blocked,
            )
            await self._session.commit()
            logger.error(
                "user_broadcast_failed",
                broadcast_id=str(broadcast_id),
                error=str(exc),
            )
