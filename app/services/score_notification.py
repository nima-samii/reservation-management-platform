"""Score-change notification delivery.

Runs OUT-OF-BAND from the score transaction (in its own session, via a delayed
one-off scheduler job) so a slow or failing Telegram send can never block or
roll back a score change. Idempotency is enforced at the DB level: a row is
claimed (pending → sending) before sending and stamped with a terminal status
afterwards, so it is delivered at most once even if the job runs twice.
"""
import html
import uuid

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.score import NotifyStatus, ScoreTransactionType
from app.repositories.score import ScoreTransactionRepository
from app.repositories.user import UserRepository
from app.services.notification import NotificationService

logger = get_logger(__name__)

# Human-readable fallback when a transaction carries no explicit reason.
_REASON_FALLBACK: dict[str, str] = {
    ScoreTransactionType.RESERVATION_REWARD.value: "Reservation reward",
    ScoreTransactionType.RESERVATION_CANCELLATION.value: "Reservation cancelled",
    ScoreTransactionType.NO_SHOW_PENALTY.value: "No-show penalty",
    ScoreTransactionType.ADMIN_ADJUSTMENT.value: "Score adjusted by an admin",
}


class ScoreNotificationService:
    """Delivers a single score-change DM, given a transaction id."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._tx_repo = ScoreTransactionRepository(session)
        self._user_repo = UserRepository(session)
        self._notif = NotificationService(bot)

    async def deliver(self, transaction_id: uuid.UUID) -> None:
        """Load the transaction + user, claim it, send the DM, record the outcome.

        Safe to call more than once for the same id — only the first claim sends.
        Never raises for a delivery failure; the score change has already committed.
        """
        if not settings.SCORE_CHANGE_NOTIFICATIONS_ENABLED:
            return

        tx = await self._tx_repo.get_with_user(transaction_id)
        if tx is None:
            logger.warning("score_notify_missing", transaction_id=str(transaction_id))
            return
        if tx.notify_status != NotifyStatus.PENDING.value:
            # Already claimed/delivered by an earlier run — nothing to do.
            return

        user = tx.user
        if user is None or user.bot_blocked:
            await self._tx_repo.mark_notified(transaction_id, NotifyStatus.SKIPPED)
            await self._session.commit()
            return

        # Win the claim before doing any I/O so a duplicate job can't double-send.
        claimed = await self._tx_repo.claim_for_notification(transaction_id)
        if not claimed:
            return
        await self._session.commit()

        text = self._format(tx.transaction_type, tx.score_delta, tx.reason, user.participation_score)

        try:
            success, error = await self._notif.send(user.telegram_id, text)
        except TelegramForbiddenError as exc:
            await self._user_repo.mark_bot_blocked(user.id)
            await self._tx_repo.mark_notified(transaction_id, NotifyStatus.FAILED)
            await self._session.commit()
            logger.info(
                "score_notify_blocked",
                transaction_id=str(transaction_id),
                user_id=str(user.id),
                error=str(exc),
            )
            return

        status = NotifyStatus.SENT if success else NotifyStatus.FAILED
        await self._tx_repo.mark_notified(transaction_id, status)
        await self._session.commit()

        if success:
            logger.info(
                "score_notify_sent",
                transaction_id=str(transaction_id),
                user_id=str(user.id),
                delta=tx.score_delta,
            )
        else:
            logger.warning(
                "score_notify_failed",
                transaction_id=str(transaction_id),
                user_id=str(user.id),
                error=error,
            )

    @staticmethod
    def _format(transaction_type: str, delta: int, reason: str | None, new_score: int) -> str:
        """Sign-aware, HTML-safe score-change message."""
        clean_reason = (reason or "").strip() or _REASON_FALLBACK.get(
            transaction_type, "Score updated"
        )
        clean_reason = html.escape(clean_reason)

        if delta > 0:
            headline = f"🎉 You received <b>+{delta}</b> point(s)!"
        else:
            headline = f"⚠️ You lost <b>{abs(delta)}</b> point(s)."

        return (
            f"<b>Score Update</b>\n\n"
            f"{headline}\n"
            f"Reason: {clean_reason}\n\n"
            f"Your current score: <b>{new_score}</b>"
        )
