"""Score-change notification delivery.

Runs OUT-OF-BAND from the score transaction (in its own session, via a delayed
one-off scheduler job) so a slow or failing Telegram send can never block or
roll back a score change. Idempotency is enforced at the DB level: a row is
claimed (pending → sending) before sending and stamped with a terminal status
afterwards, so it is delivered at most once even if the job runs twice.
"""
import html
import uuid

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.reservation import AttendanceStatus, Reservation
from app.db.models.score import NotifyStatus, ScoreTransactionType
from app.repositories.reservation import ReservationRepository
from app.repositories.score import ScoreTransactionRepository
from app.repositories.user import UserRepository
from app.services.notification import NotificationService

logger = get_logger(__name__)

TZ = pytz.timezone(settings.TIMEZONE)

# Human-readable fallback when a transaction carries no explicit reason.
_REASON_FALLBACK: dict[str, str] = {
    ScoreTransactionType.RESERVATION_REWARD.value: "Reservation reward",
    ScoreTransactionType.RESERVATION_CANCELLATION.value: "Reservation cancelled",
    ScoreTransactionType.NO_SHOW_PENALTY.value: "No-show penalty",
    ScoreTransactionType.ADMIN_ADJUSTMENT.value: "Score adjusted by an admin",
    # Defensive only — record_attendance requires a non-blank reason, so an
    # attendance row should never reach this table.
    ScoreTransactionType.ATTENDANCE_SCORE.value: "Attendance recorded by an admin",
}

# The outcome line for an attendance decision. Deliberately says nothing about
# points: the score is a separate, admin-entered number, so an absence is not
# necessarily a penalty and an attendance is not necessarily a reward.
_ATTENDANCE_LINE: dict[str, str] = {
    AttendanceStatus.ATTENDED.value: "✅ You attended this session.",
    AttendanceStatus.ABSENT.value: (
        "❌ You were marked as not having attended this session."
    ),
}


class ScoreNotificationService:
    """Delivers a single score-change DM, given a transaction id."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._session = session
        self._tx_repo = ScoreTransactionRepository(session)
        self._res_repo = ReservationRepository(session)
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

        # Include the linked reservation's slot details (date/time/channel) when
        # the transaction is tied to one — e.g. a no-show penalty.
        reservation = None
        if tx.reservation_id is not None:
            reservation = await self._res_repo.get_reservation_with_details(
                tx.reservation_id
            )

        # For an attendance decision the outcome is half the message and cannot
        # be inferred from the delta — an absence may still carry points. The
        # reservation column is authoritative; the ledger row's `meta` mirror is
        # the fallback, because score_transactions.reservation_id is
        # ON DELETE SET NULL and the row can outlive the reservation.
        attendance_status: str | None = None
        if tx.transaction_type == ScoreTransactionType.ATTENDANCE_SCORE.value:
            attendance_status = getattr(reservation, "attendance_status", None) or (
                tx.meta or {}
            ).get("attendance_status")

        text = self._format(
            tx.transaction_type,
            tx.score_delta,
            tx.reason,
            user.participation_score,
            reservation,
            attendance_status,
        )

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
    def _format(
        transaction_type: str,
        delta: int,
        reason: str | None,
        new_score: int,
        reservation: Reservation | None = None,
        attendance_status: str | None = None,
    ) -> str:
        """Sign-aware, HTML-safe score-change message.

        When ``reservation`` is provided (the transaction is tied to a slot, e.g.
        an attendance decision) its date/time/channel are appended so the user
        knows exactly which reservation the change refers to.

        ``attendance_status`` turns this into an attendance message: the outcome
        is stated on its own line above the score, because the two are
        independent and the outcome is the half the number cannot express.
        """
        clean_reason = (reason or "").strip() or _REASON_FALLBACK.get(
            transaction_type, "Score updated"
        )
        clean_reason = html.escape(clean_reason)

        if delta > 0:
            headline = f"🎉 You received <b>+{delta}</b> point(s)!"
        elif delta < 0:
            headline = f"⚠️ You lost <b>{abs(delta)}</b> point(s)."
        else:
            # Zero is a real decision an admin can record — "you attended, it
            # was worth nothing" — not a no-op. With only the two sign branches
            # above it rendered as "You lost 0 point(s)".
            headline = "ℹ️ Your score is unchanged (<b>0</b> points)."

        is_attendance = transaction_type == ScoreTransactionType.ATTENDANCE_SCORE.value
        outcome_line = _ATTENDANCE_LINE.get(attendance_status or "")

        text = f"<b>{'Session Attendance' if is_attendance else 'Score Update'}</b>\n\n"
        if outcome_line:
            text += f"{outcome_line}\n"
        text += f"{headline}\nReason: {clean_reason}\n"

        if reservation is not None and reservation.slot is not None:
            slot_local = reservation.slot.slot_datetime.astimezone(TZ)
            channel_name = (
                html.escape(reservation.channel.name) if reservation.channel else ""
            )
            text += (
                f"\n📅 Date: <b>{slot_local.strftime('%A, %d %B %Y')}</b>\n"
                f"🕐 Time: <b>{slot_local.strftime('%I:%M %p')}</b>\n"
                f"📡 Channel: {channel_name}\n"
            )

        text += f"\nYour current score: <b>{new_score}</b>"
        return text
