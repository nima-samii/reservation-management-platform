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
_SCORE_POLICY: dict[ScoreTransactionType, int] = {
    ScoreTransactionType.RESERVATION_REWARD: +1,
    ScoreTransactionType.RESERVATION_CANCELLATION: -1,
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

    async def award_reservation_reward(
        self,
        user_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> ScoreTransaction:
        """Grant +1 when a reservation is successfully created."""
        delta = _SCORE_POLICY[ScoreTransactionType.RESERVATION_REWARD]
        return await self._record(
            user_id=user_id,
            transaction_type=ScoreTransactionType.RESERVATION_REWARD,
            delta=delta,
            reservation_id=reservation_id,
        )

    async def rollback_cancellation(
        self,
        user_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> ScoreTransaction:
        """Deduct -1 when a reservation is cancelled (anti-abuse rollback)."""
        delta = _SCORE_POLICY[ScoreTransactionType.RESERVATION_CANCELLATION]
        return await self._record(
            user_id=user_id,
            transaction_type=ScoreTransactionType.RESERVATION_CANCELLATION,
            delta=delta,
            reservation_id=reservation_id,
        )

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
