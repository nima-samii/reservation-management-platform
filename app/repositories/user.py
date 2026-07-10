import random
import string
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = (
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.country_rel))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_public_code(self, code: str) -> User | None:
        return await self.first_by(public_user_code=code)

    async def exists_by_telegram_id(self, telegram_id: int) -> bool:
        stmt = select(User.id).where(User.telegram_id == telegram_id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def generate_unique_code(self) -> str:
        while True:
            code = "".join(random.choices(string.digits, k=6))
            if not await self.first_by(public_user_code=code):
                return code

    async def mark_bot_blocked(self, user_id: uuid.UUID) -> None:
        """Flag a user as having blocked the bot so future broadcasts skip them."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(bot_blocked=True)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def apply_score_delta(self, user_id: uuid.UUID, delta: int) -> None:
        """Atomically increment or decrement participation_score without a read-modify-write."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(participation_score=User.participation_score + delta)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def set_last_reservation_at(self, user_id: uuid.UUID, when: datetime) -> None:
        """Refresh the inactivity-reminder reset anchor. Call only on a
        successful reservation create — never on cancellation."""
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(last_reservation_at=when)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def mark_inactivity_reminder_sent(self, user_id: uuid.UUID, when: datetime) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(last_inactivity_reminder_sent_at=when)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)

    async def get_inactivity_reminder_candidates(
        self,
        *,
        now: datetime,
        threshold_days: int,
        after_id: uuid.UUID | None,
        limit: int,
    ) -> list[tuple[uuid.UUID, int]]:
        """Users overdue for an inactivity reminder, keyset-paginated by id.

        Loads only (id, telegram_id) — never a full User row — since the scan
        can span the whole table. Eligibility is expressed as an explicit
        "next due" date (``anchor + threshold_days``) rather than shifting
        ``now`` back by the threshold and comparing timestamps directly —
        same result, but reads as the actual business rule: a reminder is due
        once ``threshold_days`` have passed since the anchor (the last
        reservation, or the last reminder if that's later). A fresh
        reservation always resets the cycle regardless of any past reminder.
        """
        cycle = timedelta(days=threshold_days)
        conditions = [
            User.last_reservation_at.isnot(None),
            User.last_reservation_at + cycle <= now,
            User.is_banned.is_(False),
            User.bot_blocked.is_(False),
            or_(
                User.last_inactivity_reminder_sent_at.is_(None),
                User.last_inactivity_reminder_sent_at <= User.last_reservation_at,
                User.last_inactivity_reminder_sent_at + cycle <= now,
            ),
        ]
        if after_id is not None:
            conditions.append(User.id > after_id)

        stmt = (
            select(User.id, User.telegram_id)
            .where(and_(*conditions))
            .order_by(User.id)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(row.id, row.telegram_id) for row in result.all()]

    async def create(
        self,
        *,
        telegram_id: int,
        full_name: str,
        username: str | None = None,
        gender: str | None = None,
        country_id: str | None = None,
    ) -> User:
        code = await self.generate_unique_code()
        user = User(
            telegram_id=telegram_id,
            public_user_code=code,
            full_name=full_name,
            username=username,
            gender=gender,
            country_id=country_id,
        )
        return await self.save(user)

    async def get_by_uuid_with_country(self, user_id: uuid.UUID) -> User | None:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.country_rel))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def admin_list(
        self,
        *,
        search: str | None = None,
        country_id: uuid.UUID | None = None,
        gender: str | None = None,
        is_banned: bool | None = None,
        is_active: bool | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[User], int]:
        filters: list = []

        if search:
            term = f"%{search}%"
            filters.append(
                or_(
                    User.full_name.ilike(term),
                    User.username.ilike(term),
                    User.public_user_code.ilike(term),
                )
            )
        if country_id is not None:
            filters.append(User.country_id == country_id)
        if gender is not None:
            filters.append(User.gender == gender)
        if is_banned is not None:
            filters.append(User.is_banned == is_banned)
        if is_active is not None:
            filters.append(User.is_active == is_active)

        where_clause = and_(*filters) if filters else true()

        count_stmt = select(func.count(User.id)).where(where_clause)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        sort_column = {
            "score": User.participation_score,
            "name": User.full_name,
            "created_at": User.created_at,
        }.get(sort_by, User.created_at)

        sort_expr = sort_column.asc() if order == "asc" else sort_column.desc()

        data_stmt = (
            select(User)
            .where(where_clause)
            .options(selectinload(User.country_rel))
            .order_by(sort_expr)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await self.session.execute(data_stmt)
        return list(result.scalars().all()), total
