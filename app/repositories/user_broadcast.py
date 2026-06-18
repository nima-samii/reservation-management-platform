import uuid
from datetime import datetime

import pytz
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user_broadcast import (
    RecipientStatus,
    UserBroadcast,
    UserBroadcastRecipient,
    UserBroadcastStatus,
)
from app.repositories.base import BaseRepository

TZ = pytz.timezone(settings.TIMEZONE)


class UserBroadcastRepository(BaseRepository[UserBroadcast]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(UserBroadcast, session)

    async def create(
        self,
        *,
        message: str,
        parse_mode: str,
        audience_type: str,
        created_by: str,
        total_recipients: int,
    ) -> UserBroadcast:
        entry = UserBroadcast(
            message=message,
            parse_mode=parse_mode,
            audience_type=audience_type,
            status=UserBroadcastStatus.PENDING.value,
            total_recipients=total_recipients,
            created_by=created_by,
        )
        return await self.save(entry)

    async def mark_processing(self, broadcast_id: uuid.UUID) -> None:
        stmt = (
            update(UserBroadcast)
            .where(UserBroadcast.id == broadcast_id)
            .values(
                status=UserBroadcastStatus.PROCESSING.value,
                started_at=datetime.now(TZ),
            )
        )
        await self.session.execute(stmt)

    async def update_counts(
        self,
        broadcast_id: uuid.UUID,
        *,
        success_count: int,
        failed_count: int,
        blocked_count: int,
    ) -> None:
        stmt = (
            update(UserBroadcast)
            .where(UserBroadcast.id == broadcast_id)
            .values(
                success_count=success_count,
                failed_count=failed_count,
                blocked_count=blocked_count,
            )
        )
        await self.session.execute(stmt)

    async def mark_finished(
        self,
        broadcast_id: uuid.UUID,
        *,
        status: UserBroadcastStatus,
        success_count: int,
        failed_count: int,
        blocked_count: int,
    ) -> None:
        stmt = (
            update(UserBroadcast)
            .where(UserBroadcast.id == broadcast_id)
            .values(
                status=status.value,
                success_count=success_count,
                failed_count=failed_count,
                blocked_count=blocked_count,
                completed_at=datetime.now(TZ),
            )
        )
        await self.session.execute(stmt)

    async def admin_list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[UserBroadcast], int]:
        """Paginated broadcast history, newest first."""
        total = (
            await self.session.execute(select(func.count(UserBroadcast.id)))
        ).scalar() or 0

        stmt = (
            select(UserBroadcast)
            .order_by(UserBroadcast.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total


class UserBroadcastRecipientRepository(BaseRepository[UserBroadcastRecipient]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(UserBroadcastRecipient, session)

    async def bulk_create(
        self,
        broadcast_id: uuid.UUID,
        recipients: list[tuple[uuid.UUID, int]],
    ) -> int:
        """Snapshot the audience into recipient rows (status=pending). Returns count."""
        if not recipients:
            return 0
        rows = [
            {
                "id": uuid.uuid4(),
                "broadcast_id": broadcast_id,
                "user_id": user_id,
                "telegram_id": telegram_id,
                "status": RecipientStatus.PENDING.value,
            }
            for user_id, telegram_id in recipients
        ]
        await self.session.execute(insert(UserBroadcastRecipient), rows)
        return len(rows)

    async def get_pending(self, broadcast_id: uuid.UUID) -> list[UserBroadcastRecipient]:
        stmt = select(UserBroadcastRecipient).where(
            UserBroadcastRecipient.broadcast_id == broadcast_id,
            UserBroadcastRecipient.status == RecipientStatus.PENDING.value,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_sent(self, recipient_id: uuid.UUID) -> None:
        await self._set_status(recipient_id, RecipientStatus.SENT, sent_at=datetime.now(TZ))

    async def mark_blocked(self, recipient_id: uuid.UUID, error_message: str) -> None:
        await self._set_status(recipient_id, RecipientStatus.BLOCKED, error_message=error_message)

    async def mark_failed(self, recipient_id: uuid.UUID, error_message: str) -> None:
        await self._set_status(recipient_id, RecipientStatus.FAILED, error_message=error_message)

    async def _set_status(
        self,
        recipient_id: uuid.UUID,
        status: RecipientStatus,
        *,
        error_message: str | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status.value}
        if error_message is not None:
            values["error_message"] = error_message[:500]
        if sent_at is not None:
            values["sent_at"] = sent_at
        stmt = (
            update(UserBroadcastRecipient)
            .where(UserBroadcastRecipient.id == recipient_id)
            .values(**values)
        )
        await self.session.execute(stmt)
