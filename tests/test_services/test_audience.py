"""DB-backed tests for the user-broadcast audience resolver and history repo.

Requires the test Postgres database configured in tests/conftest.py.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.channel import Channel
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.db.models.user_broadcast import UserBroadcastAudience, UserBroadcastStatus
from app.repositories.user_broadcast import UserBroadcastRepository
from app.services.audience import AudienceResolver

_code_seq = 0


def _next_code() -> str:
    global _code_seq
    _code_seq += 1
    return f"{_code_seq:06d}"


async def _make_user(
    session,
    *,
    telegram_id: int,
    is_active: bool = True,
    is_banned: bool = False,
    bot_blocked: bool = False,
) -> User:
    user = User(
        telegram_id=telegram_id,
        public_user_code=_next_code(),
        full_name=f"User {telegram_id}",
        is_active=is_active,
        is_banned=is_banned,
        bot_blocked=bot_blocked,
    )
    session.add(user)
    await session.flush()
    return user


async def _give_reservation(session, user: User) -> None:
    channel = Channel(name="Ch", telegram_channel_id=-1000 - user.telegram_id, capacity=100)
    session.add(channel)
    await session.flush()
    slot = ReservationSlot(
        slot_datetime=datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc),
        channel_id=channel.id,
    )
    session.add(slot)
    await session.flush()
    res = Reservation(
        user_id=user.id,
        slot_id=slot.id,
        channel_id=channel.id,
        status=ReservationStatus.ACTIVE.value,
    )
    session.add(res)
    await session.flush()


# ── all_users ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_users_excludes_blocked(db_session):
    await _make_user(db_session, telegram_id=1)
    await _make_user(db_session, telegram_id=2)
    await _make_user(db_session, telegram_id=3, bot_blocked=True)

    resolver = AudienceResolver(db_session)
    count = await resolver.count(UserBroadcastAudience.ALL_USERS.value)
    recipients = await resolver.fetch_recipients(UserBroadcastAudience.ALL_USERS.value)

    assert count == 2
    assert len(recipients) == 2
    assert {tg for _, tg in recipients} == {1, 2}


# ── active_users ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_users_filters(db_session):
    await _make_user(db_session, telegram_id=10)  # active
    await _make_user(db_session, telegram_id=11, is_active=False)  # inactive
    await _make_user(db_session, telegram_id=12, is_banned=True)  # banned
    await _make_user(db_session, telegram_id=13, bot_blocked=True)  # blocked

    resolver = AudienceResolver(db_session)
    recipients = await resolver.fetch_recipients(UserBroadcastAudience.ACTIVE_USERS.value)

    assert {tg for _, tg in recipients} == {10}


# ── users_with_reservations ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_users_with_reservations(db_session):
    u1 = await _make_user(db_session, telegram_id=20)
    await _make_user(db_session, telegram_id=21)  # no reservation
    u3 = await _make_user(db_session, telegram_id=22, bot_blocked=True)

    await _give_reservation(db_session, u1)
    await _give_reservation(db_session, u3)  # has reservation but blocked

    resolver = AudienceResolver(db_session)
    recipients = await resolver.fetch_recipients(
        UserBroadcastAudience.USERS_WITH_RESERVATIONS.value
    )

    assert {tg for _, tg in recipients} == {20}


@pytest.mark.asyncio
async def test_unknown_audience_raises(db_session):
    resolver = AudienceResolver(db_session)
    with pytest.raises(ValueError):
        await resolver.count("nonsense")


# ── history repository ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_pagination_and_order(db_session):
    repo = UserBroadcastRepository(db_session)
    for i in range(3):
        await repo.create(
            message=f"m{i}",
            parse_mode="HTML",
            audience_type=UserBroadcastAudience.ALL_USERS.value,
            created_by="admin",
            total_recipients=i,
        )
    await db_session.flush()

    page1, total = await repo.admin_list(page=1, page_size=2)
    assert total == 3
    assert len(page1) == 2
    # newest first
    assert page1[0].created_at >= page1[1].created_at

    page2, _ = await repo.admin_list(page=2, page_size=2)
    assert len(page2) == 1
