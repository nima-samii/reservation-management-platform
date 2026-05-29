import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.score import ScoreTransaction, ScoreTransactionType
from app.repositories.base import BaseRepository


class ScoreTransactionRepository(BaseRepository[ScoreTransaction]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ScoreTransaction, session)

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        transaction_type: ScoreTransactionType,
        score_delta: int,
        reservation_id: uuid.UUID | None = None,
        reason: str | None = None,
        meta: dict | None = None,
    ) -> ScoreTransaction:
        tx = ScoreTransaction(
            user_id=user_id,
            reservation_id=reservation_id,
            transaction_type=transaction_type,
            score_delta=score_delta,
            reason=reason,
            meta=meta,
        )
        return await self.save(tx)

    async def get_user_history(
        self, user_id: uuid.UUID, limit: int = 50
    ) -> list[ScoreTransaction]:
        stmt = (
            select(ScoreTransaction)
            .where(ScoreTransaction.user_id == user_id)
            .order_by(ScoreTransaction.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
