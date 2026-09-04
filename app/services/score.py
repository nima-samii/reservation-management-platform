"""Participation Score service — all score mutations go through here.

Every modification creates an immutable ScoreTransaction row (the audit trail)
and atomically updates the cached users.participation_score column.
The two operations share the caller's SQLAlchemy session, so they commit or
roll back together with whatever enclosing transaction called us.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.score import ScoreTransaction, ScoreTransactionType
from app.repositories.score import ScoreTransactionRepository
from app.repositories.user import UserRepository

logger = get_logger(__name__)

# Canonical delta for each transaction type.
# Add new types here — no logic changes needed elsewhere.
#
# RESERVATION_REWARD (+1) and RESERVATION_CANCELLATION (-1) are gone: booking
# and cancelling no longer move the score, so there is no policy left to state.
# Their enum members remain, because ledger rows written under the old rules
# still exist and still have to render in the score history.
#
# ATTENDANCE_SCORE is absent by design, not omission — the admin supplies the
# number, and that is the point of the feature.
_SCORE_POLICY: dict[ScoreTransactionType, int] = {
    ScoreTransactionType.NO_SHOW_PENALTY: -1,
    # ADMIN_ADJUSTMENT uses a caller-supplied delta — not in this table
}


class ParticipationScoreService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tx_repo = ScoreTransactionRepository(session)
        self._user_repo = UserRepository(session)

    async def _record(
        self,
        *,
        user_id: uuid.UUID,
        transaction_type: ScoreTransactionType,
        delta: int,
        reservation_id: uuid.UUID | None = None,
        reason: str | None = None,
        meta: dict | None = None,
    ) -> ScoreTransaction:
        """Insert a transaction row and update the cached score atomically."""
        tx = await self._tx_repo.create(
            user_id=user_id,
            transaction_type=transaction_type,
            score_delta=delta,
            reservation_id=reservation_id,
            reason=reason,
            meta=meta,
        )
        await self._user_repo.apply_score_delta(user_id, delta)
        logger.info(
            "score_updated",
            user_id=str(user_id),
            type=transaction_type,
            delta=delta,
        )
        return tx

    # award_reservation_reward / rollback_cancellation were deleted rather than
    # left unused. Booking a session and cancelling one no longer change the
    # score, and a method that still implements the old rule is an invitation
    # to call it back into existence from a new flow.

    async def apply_no_show_penalty(
        self,
        user_id: uuid.UUID,
        reservation_id: uuid.UUID,
        reason: str | None = None,
    ) -> ScoreTransaction:
        """Deduct -1 for a no-show. Called by admin or scheduler."""
        delta = _SCORE_POLICY[ScoreTransactionType.NO_SHOW_PENALTY]
        return await self._record(
            user_id=user_id,
            transaction_type=ScoreTransactionType.NO_SHOW_PENALTY,
            delta=delta,
            reservation_id=reservation_id,
            reason=reason,
        )

    async def apply_attendance_score(
        self,
        user_id: uuid.UUID,
        reservation_id: uuid.UUID,
        delta: int,
        reason: str,
        meta: dict | None = None,
    ) -> ScoreTransaction:
        """Record the score an admin entered with an attendance decision.

        Not in ``_SCORE_POLICY``: the whole point of the feature is that the
        admin chooses the number, and that it is unconstrained by the outcome —
        an attendance may be worth nothing and an absence may still be worth
        points.

        A delta of 0 is written like any other. It is a decision the user is
        told about, so it needs its audit row; skipping it would make "attended,
        no points" the one outcome with no trace.

        Callers must have already won
        :meth:`ReservationRepository.claim_attendance_decision` — this method
        has no idempotency of its own.
        """
        return await self._record(
            user_id=user_id,
            transaction_type=ScoreTransactionType.ATTENDANCE_SCORE,
            delta=delta,
            reservation_id=reservation_id,
            reason=reason,
            meta=meta,
        )

    async def apply_admin_adjustment(
        self,
        user_id: uuid.UUID,
        delta: int,
        reason: str,
        meta: dict | None = None,
    ) -> ScoreTransaction:
        """Manual score correction by an admin. Delta may be positive or negative."""
        return await self._record(
            user_id=user_id,
            transaction_type=ScoreTransactionType.ADMIN_ADJUSTMENT,
            delta=delta,
            reason=reason,
            meta=meta,
        )

    async def get_user_history(
        self, user_id: uuid.UUID, limit: int = 50
    ) -> list[ScoreTransaction]:
        return await self._tx_repo.get_user_history(user_id, limit)
