"""User-broadcast orchestration: create a broadcast, snapshot its audience, and
deliver to every recipient in the background with throttling, per-recipient
delivery tracking, and blocked-bot detection.

Sprint 3 additions (no change to existing text-delivery behavior):
- media-aware delivery (text / photo / document) via a single ``_send_one``;
- drafts (created, never snapshotted, editable, launched later);
- scheduled + recurring broadcasts that snapshot the audience at execution time
  so the audience is fresh when it actually fires.

Reuses the SegmentationService for audience resolution and the project's single
Bot instance for sending — delivery logic is not duplicated.
"""
import asyncio
import uuid

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user_broadcast import MediaType, UserBroadcast, UserBroadcastStatus
from app.repositories.user import UserRepository
from app.repositories.user_broadcast import (
    UserBroadcastRecipientRepository,
    UserBroadcastRepository,
)
from app.services.segmentation import (
    SegmentFilter,
    SegmentationService,
    quick_segment_to_filter,
)

logger = get_logger(__name__)

_RUNNABLE = (
    UserBroadcastStatus.PENDING.value,
    UserBroadcastStatus.PROCESSING.value,
    UserBroadcastStatus.SCHEDULED.value,
)


class UserBroadcastService:
    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._bot = bot
        self._segmentation = SegmentationService(session)
        self._broadcast_repo = UserBroadcastRepository(session)
        self._recipient_repo = UserBroadcastRecipientRepository(session)
        self._user_repo = UserRepository(session)

    # ── Audience helpers ────────────────────────────────────────────────────

    def _effective_filter(self, broadcast: UserBroadcast) -> SegmentFilter:
        """Reconstruct the segment for (re-)resolution. Stored ``filters`` win;
        otherwise fall back to the quick-segment audience_type."""
        if broadcast.filters:
            return SegmentFilter(**broadcast.filters)
        return quick_segment_to_filter(broadcast.audience_type)

    async def _snapshot(self, broadcast: UserBroadcast, segment_filter: SegmentFilter) -> int:
        """Resolve the audience and persist one recipient row per user."""
        recipients = await self._segmentation.fetch_recipients(segment_filter)
        await self._recipient_repo.bulk_create(broadcast.id, recipients)
        await self._broadcast_repo.set_total_recipients(broadcast.id, len(recipients))
        broadcast.total_recipients = len(recipients)
        return len(recipients)

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
        status: str = UserBroadcastStatus.PENDING.value,
        media_type: str = MediaType.TEXT.value,
        media_file_id: str | None = None,
        scheduled_for=None,
        template_id: uuid.UUID | None = None,
    ) -> UserBroadcast:
        """Create the broadcast row. Recipients are snapshotted now ONLY for an
        immediate send (status=pending). Drafts and scheduled broadcasts are not
        snapshotted here — drafts never get recipient rows, and scheduled ones
        snapshot at execution so their audience is fresh.
        """
        broadcast = await self._broadcast_repo.create(
            message=message,
            parse_mode=parse_mode,
            audience_type=audience_type,
            filters=filters_payload,
            created_by=created_by,
            status=status,
            media_type=media_type,
            media_file_id=media_file_id,
            scheduled_for=scheduled_for,
            template_id=template_id,
        )
        if status == UserBroadcastStatus.PENDING.value:
            await self._snapshot(broadcast, segment_filter)
        await self._session.commit()

        logger.info(
            "user_broadcast_created",
            broadcast_id=str(broadcast.id),
            audience=audience_type,
            status=status,
            media_type=media_type,
            recipients=broadcast.total_recipients,
            created_by=created_by,
        )
        return broadcast

    async def launch_draft_now(self, broadcast: UserBroadcast) -> None:
        """Transition a draft to an immediate send: snapshot + mark pending."""
        await self._snapshot(broadcast, self._effective_filter(broadcast))
        await self._broadcast_repo.set_status(broadcast.id, UserBroadcastStatus.PENDING.value)
        await self._session.commit()

    async def create_recurring_run(self, source: UserBroadcast) -> UserBroadcast:
        """Clone a recurring rule's source broadcast into a fresh run (pending,
        snapshotted). Historical runs are never overwritten."""
        run = await self._broadcast_repo.create(
            message=source.message,
            parse_mode=source.parse_mode,
            audience_type=source.audience_type,
            filters=source.filters,
            created_by=source.created_by,
            status=UserBroadcastStatus.PENDING.value,
            media_type=source.media_type,
            media_file_id=source.media_file_id,
            template_id=source.template_id,
        )
        await self._snapshot(run, self._effective_filter(source))
        await self._session.commit()
        logger.info(
            "user_broadcast_recurring_run_created",
            source_id=str(source.id),
            run_id=str(run.id),
            recipients=run.total_recipients,
        )
        return run

    # ── Delivery (background path) ──────────────────────────────────────────

    async def _send_one(self, broadcast: UserBroadcast, telegram_id: int, parse_mode) -> None:
        """Dispatch a single message by media type. The text path is unchanged
        from Sprint 1; photo/document attach the stored Telegram file_id and use
        the message as the caption."""
        media_type = broadcast.media_type or MediaType.TEXT.value
        if media_type == MediaType.PHOTO.value:
            await self._bot.send_photo(
                chat_id=telegram_id,
                photo=broadcast.media_file_id,
                caption=broadcast.message or None,
                parse_mode=parse_mode,
            )
        elif media_type == MediaType.DOCUMENT.value:
            await self._bot.send_document(
                chat_id=telegram_id,
                document=broadcast.media_file_id,
                caption=broadcast.message or None,
                parse_mode=parse_mode,
            )
        else:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=broadcast.message,
                parse_mode=parse_mode,
            )

    #: How many times to honor a Telegram flood-wait (429) for one recipient
    #: before giving up on that recipient.
    _MAX_FLOOD_RETRIES = 5

    async def _deliver_one(
        self, broadcast: UserBroadcast, recipient, parse_mode
    ) -> str:
        """Deliver to a single recipient, honoring Telegram flood-control.

        Returns one of ``"sent"`` / ``"blocked"`` / ``"failed"``. On
        ``TelegramRetryAfter`` (HTTP 429) the delivery loop backs off for the
        server-mandated interval and retries the SAME recipient — the recipient
        row is left untouched (still PENDING) during the wait, so a flood wait
        never falsely marks recipients FAILED and never drops their message.
        Because ``get_pending`` only re-selects PENDING rows, mishandling this
        previously meant flood-hit users were silently never delivered to.
        """
        for attempt in range(1, self._MAX_FLOOD_RETRIES + 1):
            try:
                await self._send_one(broadcast, recipient.telegram_id, parse_mode)
                await self._recipient_repo.mark_sent(recipient.id)
                return "sent"
            except TelegramRetryAfter as exc:
                logger.warning(
                    "user_broadcast_flood_wait",
                    broadcast_id=str(broadcast.id),
                    retry_after=exc.retry_after,
                    attempt=attempt,
                )
                await asyncio.sleep(exc.retry_after + 1)
                continue
            except TelegramForbiddenError as exc:
                await self._recipient_repo.mark_blocked(recipient.id, str(exc))
                await self._user_repo.mark_bot_blocked(recipient.user_id)
                await self._session.commit()
                return "blocked"
            except TelegramAPIError as exc:
                await self._recipient_repo.mark_failed(recipient.id, str(exc))
                return "failed"
            except Exception as exc:  # never let one recipient kill the run
                await self._recipient_repo.mark_failed(recipient.id, str(exc))
                logger.warning(
                    "user_broadcast_unexpected_error",
                    broadcast_id=str(broadcast.id),
                    error=str(exc),
                )
                return "failed"

        # Telegram kept asking us to wait beyond our retry budget — record it so
        # the recipient isn't stuck PENDING forever, and move on.
        await self._recipient_repo.mark_failed(
            recipient.id, "flood_wait_retries_exhausted"
        )
        return "failed"

    async def run_broadcast(self, broadcast_id: uuid.UUID) -> None:
        """Deliver a runnable broadcast. Scheduled broadcasts are snapshotted
        here (fresh audience). Only PENDING rows are re-sent on resume."""
        broadcast = await self._broadcast_repo.get_by_id(broadcast_id)
        if broadcast is None:
            logger.warning("user_broadcast_missing", broadcast_id=str(broadcast_id))
            return
        if broadcast.status not in _RUNNABLE:
            logger.info(
                "user_broadcast_not_runnable",
                broadcast_id=str(broadcast_id),
                status=broadcast.status,
            )
            return

        # Scheduled broadcasts have no recipients yet — resolve them now.
        if broadcast.status == UserBroadcastStatus.SCHEDULED.value:
            await self._snapshot(broadcast, self._effective_filter(broadcast))

        await self._broadcast_repo.mark_processing(broadcast_id)
        await self._session.commit()

        parse_mode = None if broadcast.parse_mode == "plain" else broadcast.parse_mode
        rate = max(settings.USER_BROADCAST_RATE_LIMIT, 1)
        interval = 1.0 / rate
        persist_every = rate  # roughly once per second

        success = broadcast.success_count
        failed = broadcast.failed_count
        blocked = broadcast.blocked_count

        try:
            pending = await self._recipient_repo.get_pending(broadcast_id)
            for i, recipient in enumerate(pending, start=1):
                outcome = await self._deliver_one(broadcast, recipient, parse_mode)
                if outcome == "sent":
                    success += 1
                elif outcome == "blocked":
                    blocked += 1
                else:
                    failed += 1

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
