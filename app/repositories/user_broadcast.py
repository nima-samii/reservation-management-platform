import uuid
from datetime import datetime

import pytz
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user_broadcast import (
    BroadcastRecurringRule,
    BroadcastTemplate,
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
        total_recipients: int = 0,
        filters: dict | None = None,
        status: str = UserBroadcastStatus.PENDING.value,
        media_type: str = "text",
        media_file_id: str | None = None,
        scheduled_for: datetime | None = None,
        template_id: uuid.UUID | None = None,
    ) -> UserBroadcast:
        entry = UserBroadcast(
            message=message,
            parse_mode=parse_mode,
            audience_type=audience_type,
            filters=filters,
            status=status,
            total_recipients=total_recipients,
            created_by=created_by,
            media_type=media_type,
            media_file_id=media_file_id,
            scheduled_for=scheduled_for,
            template_id=template_id,
        )
        return await self.save(entry)

    async def update_draft(self, broadcast_id: uuid.UUID, **fields) -> None:
        """Patch editable fields on a draft. Caller must guarantee status=draft."""
        allowed = {
            "message", "parse_mode", "audience_type", "filters",
            "media_type", "media_file_id", "scheduled_for",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return
        await self.session.execute(
            update(UserBroadcast).where(UserBroadcast.id == broadcast_id).values(**values)
        )

    async def set_status(self, broadcast_id: uuid.UUID, status: str) -> None:
        await self.session.execute(
            update(UserBroadcast).where(UserBroadcast.id == broadcast_id).values(status=status)
        )

    async def set_total_recipients(self, broadcast_id: uuid.UUID, total: int) -> None:
        await self.session.execute(
            update(UserBroadcast)
            .where(UserBroadcast.id == broadcast_id)
            .values(total_recipients=total)
        )

    async def get_due_scheduled(self, now: datetime) -> list[UserBroadcast]:
        """Scheduled broadcasts whose time has arrived (restart-safety net)."""
        stmt = select(UserBroadcast).where(
            UserBroadcast.status == UserBroadcastStatus.SCHEDULED.value,
            UserBroadcast.scheduled_for.is_not(None),
            UserBroadcast.scheduled_for <= now,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_scheduled(self) -> list[UserBroadcast]:
        stmt = select(UserBroadcast).where(
            UserBroadcast.status == UserBroadcastStatus.SCHEDULED.value
        )
        return list((await self.session.execute(stmt)).scalars().all())

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


class BroadcastTemplateRepository(BaseRepository[BroadcastTemplate]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BroadcastTemplate, session)

    async def create(
        self,
        *,
        name: str,
        message: str,
        parse_mode: str = "HTML",
        description: str | None = None,
        media_type: str = "text",
        media_file_id: str | None = None,
    ) -> BroadcastTemplate:
        entry = BroadcastTemplate(
            name=name,
            description=description,
            message=message,
            parse_mode=parse_mode,
            media_type=media_type,
            media_file_id=media_file_id,
        )
        return await self.save(entry)

    async def list_all(self) -> list[BroadcastTemplate]:
        stmt = select(BroadcastTemplate).order_by(BroadcastTemplate.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def update(self, template_id: uuid.UUID, **fields) -> BroadcastTemplate | None:
        allowed = {"name", "description", "message", "parse_mode", "media_type", "media_file_id"}
        values = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if values:
            await self.session.execute(
                update(BroadcastTemplate)
                .where(BroadcastTemplate.id == template_id)
                .values(**values)
            )
            await self.session.flush()
        return await self.get_by_id(template_id)


class BroadcastRecurringRuleRepository(BaseRepository[BroadcastRecurringRule]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BroadcastRecurringRule, session)

    async def create(
        self,
        *,
        broadcast_id: uuid.UUID,
        frequency: str,
        next_run_at: datetime,
        interval: int = 1,
        day_of_week: int | None = None,
        day_of_month: int | None = None,
    ) -> BroadcastRecurringRule:
        entry = BroadcastRecurringRule(
            broadcast_id=broadcast_id,
            frequency=frequency,
            interval=interval,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            next_run_at=next_run_at,
        )
        return await self.save(entry)

    async def get_due(self, now: datetime) -> list[BroadcastRecurringRule]:
        stmt = select(BroadcastRecurringRule).where(
            BroadcastRecurringRule.is_active.is_(True),
            BroadcastRecurringRule.next_run_at <= now,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_all(self) -> list[BroadcastRecurringRule]:
        stmt = select(BroadcastRecurringRule).order_by(BroadcastRecurringRule.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_next_run(self, rule_id: uuid.UUID, next_run_at: datetime) -> None:
        await self.session.execute(
            update(BroadcastRecurringRule)
            .where(BroadcastRecurringRule.id == rule_id)
            .values(next_run_at=next_run_at)
        )

    async def set_active(self, rule_id: uuid.UUID, is_active: bool) -> None:
        await self.session.execute(
            update(BroadcastRecurringRule)
            .where(BroadcastRecurringRule.id == rule_id)
            .values(is_active=is_active)
        )
