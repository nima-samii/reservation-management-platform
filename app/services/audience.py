"""Single source of truth for user-broadcast audience filtering.

Both the preview-count endpoint and the sender resolve their audience through
this resolver, so the filtering logic is never duplicated. Every audience
implicitly excludes users who have blocked the bot (bot_blocked = True).
"""
import uuid

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reservation import Reservation
from app.db.models.user import User
from app.db.models.user_broadcast import UserBroadcastAudience


class AudienceResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def build_conditions(self, audience_type: str) -> list[ColumnElement[bool]]:
        """Return the WHERE conditions on User for the given audience.

        Raises ValueError for an unknown audience so callers surface a 4xx
        rather than silently broadcasting to everyone.
        """
        # Blocked users are excluded from every audience.
        conditions: list[ColumnElement[bool]] = [User.bot_blocked.is_(False)]

        if audience_type == UserBroadcastAudience.ALL_USERS.value:
            pass
        elif audience_type == UserBroadcastAudience.ACTIVE_USERS.value:
            conditions.append(User.is_active.is_(True))
            conditions.append(User.is_banned.is_(False))
        elif audience_type == UserBroadcastAudience.USERS_WITH_RESERVATIONS.value:
            conditions.append(exists().where(Reservation.user_id == User.id))
        else:
            raise ValueError(f"Unknown audience_type: {audience_type}")

        return conditions

    async def count(self, audience_type: str) -> int:
        """Number of users matching the audience."""
        conditions = self.build_conditions(audience_type)
        stmt = select(func.count(User.id)).where(*conditions)
        return (await self.session.execute(stmt)).scalar() or 0

    async def fetch_recipients(self, audience_type: str) -> list[tuple[uuid.UUID, int]]:
        """Return (user_id, telegram_id) tuples for every matching user."""
        conditions = self.build_conditions(audience_type)
        stmt = select(User.id, User.telegram_id).where(*conditions)
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]
