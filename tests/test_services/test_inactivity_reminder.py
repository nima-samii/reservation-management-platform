"""Tests for the inactivity-reservation-reminder feature.

Eligibility query (DB-backed, `UserRepository.get_inactivity_reminder_candidates`)
covers every business rule from the spec: first reminder, threshold boundary,
repeat cadence, reset-on-new-reservation, and the banned/blocked/never-reserved
exclusions. Delivery (`InactivityReminderService`) is tested mocked, no DB, in
the same style as test_reservation_notification.py — happy path, blocked-user
detection, and non-fatal failures. The job wrapper test mirrors
test_reservation_notification.py's `test_job_wrapper_swallows_delivery_error`.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from app.db.models.user import User
from app.repositories.user import UserRepository
from app.services.inactivity_reminder import InactivityReminderService

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
THRESHOLD_DAYS = 30

_code_seq = 0


def _code() -> str:
    global _code_seq
    _code_seq += 1
    return f"{_code_seq:06d}"


async def _user(
    session,
    *,
    tg: int,
    last_reservation_at: datetime | None = None,
    last_inactivity_reminder_sent_at: datetime | None = None,
    is_banned: bool = False,
    bot_blocked: bool = False,
) -> User:
    u = User(
        telegram_id=tg,
        public_user_code=_code(),
        full_name=f"U{tg}",
        is_banned=is_banned,
        bot_blocked=bot_blocked,
        last_reservation_at=last_reservation_at,
        last_inactivity_reminder_sent_at=last_inactivity_reminder_sent_at,
    )
    session.add(u)
    await session.flush()
    return u


def _ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


async def _candidates(session, after_id=None, limit=100) -> set[int]:
    repo = UserRepository(session)
    rows = await repo.get_inactivity_reminder_candidates(
        now=NOW, threshold_days=THRESHOLD_DAYS, after_id=after_id, limit=limit
    )
    return {tg for _, tg in rows}


# ── Eligibility query ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_reminder_eligible_when_never_reminded(db_session):
    await _user(db_session, tg=1, last_reservation_at=_ago(31))
    assert await _candidates(db_session) == {1}


@pytest.mark.asyncio
async def test_not_eligible_before_threshold(db_session):
    await _user(db_session, tg=2, last_reservation_at=_ago(29))
    assert await _candidates(db_session) == set()


@pytest.mark.asyncio
async def test_eligible_exactly_at_threshold_boundary(db_session):
    await _user(db_session, tg=3, last_reservation_at=_ago(THRESHOLD_DAYS))
    assert await _candidates(db_session) == {3}


@pytest.mark.asyncio
async def test_never_reserved_is_excluded(db_session):
    await _user(db_session, tg=4, last_reservation_at=None)
    assert await _candidates(db_session) == set()


@pytest.mark.asyncio
async def test_not_eligible_when_reminded_recently(db_session):
    # Reminded 5 days ago — too soon to fire again even though the last
    # reservation is well past the threshold.
    await _user(
        db_session,
        tg=5,
        last_reservation_at=_ago(61),
        last_inactivity_reminder_sent_at=_ago(5),
    )
    assert await _candidates(db_session) == set()


@pytest.mark.asyncio
async def test_eligible_again_once_last_reminder_is_stale(db_session):
    # Reminded 31 days ago (older than the threshold) — due for reminder #2.
    await _user(
        db_session,
        tg=6,
        last_reservation_at=_ago(61),
        last_inactivity_reminder_sent_at=_ago(31),
    )
    assert await _candidates(db_session) == {6}


@pytest.mark.asyncio
async def test_recent_reservation_excludes_previously_reminded_user(db_session):
    # Reminded 40 days ago, but reserved again 10 days ago — well within the
    # threshold. The new reservation must suppress the reminder entirely.
    await _user(
        db_session,
        tg=7,
        last_reservation_at=_ago(10),
        last_inactivity_reminder_sent_at=_ago(40),
    )
    assert await _candidates(db_session) == set()


@pytest.mark.asyncio
async def test_reservation_resets_cycle_then_fires_again_later(db_session):
    # Reminded 40 days ago, reserved again 35 days ago (after that reminder),
    # and it's now been >threshold since that new reservation — a fresh
    # cycle is due, even though a reminder was already sent once before.
    await _user(
        db_session,
        tg=8,
        last_reservation_at=_ago(35),
        last_inactivity_reminder_sent_at=_ago(40),
    )
    assert await _candidates(db_session) == {8}


@pytest.mark.asyncio
async def test_banned_users_are_excluded(db_session):
    await _user(db_session, tg=9, last_reservation_at=_ago(31), is_banned=True)
    assert await _candidates(db_session) == set()


@pytest.mark.asyncio
async def test_bot_blocked_users_are_excluded(db_session):
    await _user(db_session, tg=10, last_reservation_at=_ago(31), bot_blocked=True)
    assert await _candidates(db_session) == set()


@pytest.mark.asyncio
async def test_keyset_pagination_covers_all_without_duplicates(db_session):
    for tg in range(100, 105):
        await _user(db_session, tg=tg, last_reservation_at=_ago(31))

    repo = UserRepository(db_session)
    seen: list[int] = []
    after_id = None
    while True:
        page = await repo.get_inactivity_reminder_candidates(
            now=NOW, threshold_days=THRESHOLD_DAYS, after_id=after_id, limit=2
        )
        if not page:
            break
        seen.extend(tg for _, tg in page)
        after_id = page[-1][0]

    assert sorted(seen) == [100, 101, 102, 103, 104]


# ── Delivery service ──────────────────────────────────────────────────────────


@pytest.fixture
def svc():
    s = InactivityReminderService.__new__(InactivityReminderService)
    s._session = AsyncMock()
    s._bot = AsyncMock()
    s._user_repo = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_remind_one_happy_path(svc):
    user_id = uuid.uuid4()
    outcome = await svc._remind_one(user_id, 555)

    assert outcome == "sent"
    svc._bot.send_message.assert_awaited_once()
    assert svc._bot.send_message.await_args.args[0] == 555
    svc._user_repo.mark_inactivity_reminder_sent.assert_awaited_once()
    assert svc._user_repo.mark_inactivity_reminder_sent.await_args.args[0] == user_id
    svc._user_repo.mark_bot_blocked.assert_not_called()


@pytest.mark.asyncio
async def test_remind_one_forbidden_marks_blocked(svc):
    user_id = uuid.uuid4()
    svc._bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=None, message="bot was blocked")
    )

    outcome = await svc._remind_one(user_id, 555)

    assert outcome == "blocked"
    svc._user_repo.mark_bot_blocked.assert_awaited_once_with(user_id)
    svc._user_repo.mark_inactivity_reminder_sent.assert_not_called()


@pytest.mark.asyncio
async def test_remind_one_api_error_marks_failed(svc):
    user_id = uuid.uuid4()
    svc._bot.send_message = AsyncMock(
        side_effect=TelegramAPIError(method=None, message="chat not found")
    )

    outcome = await svc._remind_one(user_id, 555)

    assert outcome == "failed"
    svc._user_repo.mark_bot_blocked.assert_not_called()
    svc._user_repo.mark_inactivity_reminder_sent.assert_not_called()


@pytest.mark.asyncio
async def test_send_due_reminders_disabled_is_noop(svc, monkeypatch):
    import app.services.inactivity_reminder as mod

    monkeypatch.setattr(mod.settings, "INACTIVITY_REMINDER_ENABLED", False)
    svc._user_repo.get_inactivity_reminder_candidates = AsyncMock()

    counts = await svc.send_due_reminders()

    assert counts == {"scanned": 0, "sent": 0, "failed": 0, "blocked": 0}
    svc._user_repo.get_inactivity_reminder_candidates.assert_not_called()


@pytest.mark.asyncio
async def test_send_due_reminders_paginates_until_exhausted(svc, monkeypatch):
    import app.services.inactivity_reminder as mod

    monkeypatch.setattr(mod.settings, "INACTIVITY_REMINDER_ENABLED", True)
    monkeypatch.setattr(mod, "_BATCH_SIZE", 2)

    ids = [(uuid.uuid4(), tg) for tg in (1, 2, 3)]
    pages = [ids[0:2], ids[2:3]]
    svc._user_repo.get_inactivity_reminder_candidates = AsyncMock(side_effect=pages)
    svc._remind_one = AsyncMock(return_value="sent")

    counts = await svc.send_due_reminders()

    assert counts == {"scanned": 3, "sent": 3, "failed": 0, "blocked": 0}
    assert svc._user_repo.get_inactivity_reminder_candidates.await_count == 2


# ── Scheduler job wrapper ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_skips_when_lock_held():
    from app.schedulers.jobs import inactivity_reminder as job_mod

    with patch.object(job_mod.redis_client, "set_nx", AsyncMock(return_value=False)), \
         patch.object(job_mod, "InactivityReminderService") as svc_cls:
        await job_mod.send_inactivity_reminders_job()

    svc_cls.assert_not_called()


@pytest.mark.asyncio
async def test_job_wrapper_swallows_service_error():
    """The job must never propagate — a failed scan can't crash the scheduler."""
    from app.schedulers.jobs import inactivity_reminder as job_mod

    failing_svc = MagicMock()
    failing_svc.send_due_reminders = AsyncMock(side_effect=RuntimeError("db down"))

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(job_mod.redis_client, "set_nx", AsyncMock(return_value=True)), \
         patch.object(job_mod.redis_client, "delete", AsyncMock()), \
         patch.object(job_mod, "AsyncSessionFactory", return_value=cm), \
         patch.object(job_mod, "InactivityReminderService", return_value=failing_svc), \
         patch.object(job_mod, "get_bot", return_value=MagicMock()):
        await job_mod.send_inactivity_reminders_job()
