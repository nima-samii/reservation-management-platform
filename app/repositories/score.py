import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.score import NotifyStatus, ScoreTransaction, ScoreTransactionType
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

    async def get_with_user(self, tx_id: uuid.UUID) -> ScoreTransaction | None:
        """Load a transaction with its user eagerly loaded (for notification delivery)."""
        stmt = (
            select(ScoreTransaction)
            .where(ScoreTransaction.id == tx_id)
            .options(selectinload(ScoreTransaction.user))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def claim_for_notification(self, tx_id: uuid.UUID) -> bool:
        """Atomically transition pending → sending. Returns True if this caller
        won the claim (idempotency guard against double-sends across jobs/instances)."""
        stmt = (
            update(ScoreTransaction)
            .where(
                ScoreTransaction.id == tx_id,
                ScoreTransaction.notify_status == NotifyStatus.PENDING.value,
            )
            .values(notify_status=NotifyStatus.SENDING.value)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return (result.rowcount or 0) > 0

    async def mark_notified(self, tx_id: uuid.UUID, status: NotifyStatus) -> None:
        """Record a terminal delivery outcome and stamp notified_at."""
        stmt = (
            update(ScoreTransaction)
            .where(ScoreTransaction.id == tx_id)
            .values(notify_status=status.value, notified_at=func.now())
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def get_user_history_paginated(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[list[ScoreTransaction], int]:
        base_where = ScoreTransaction.user_id == user_id

        count_stmt = select(func.count(ScoreTransaction.id)).where(base_where)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        data_stmt = (
            select(ScoreTransaction)
            .where(base_where)
            .order_by(ScoreTransaction.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await self.session.execute(data_stmt)
        return list(result.scalars().all()), total
