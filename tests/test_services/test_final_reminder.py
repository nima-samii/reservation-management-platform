"""Tests for the Final Live Reminder feature.

Repository (DB-backed, ``NotificationRepository.get_reservations_for_window_reminder``)
covers the forward-only window, the SENT-suppresses / FAILED-stays-eligible
dedup rule, and cross-timezone correctness. The FINAL type is verified to be
independent of PRE_SESSION / SAME_DAY. Delivery (``ReminderService._deliver_final``
and ``send_final_reminders``) is tested mocked, no DB, in the style of
test_inactivity_reminder.py. The job wrapper mirrors the inactivity job tests.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from app.core.config import settings
from app.db.models.channel import Channel
from app.db.models.notification_log import DeliveryStatus, NotificationLog, ReminderType
from app.db.models.reservation import Reservation, ReservationStatus
from app.db.models.slot import ReservationSlot
from app.db.models.user import User
from app.repositories.notification import NotificationRepository
from app.services.notification import ReminderService

BAGHDAD = pytz.timezone("Asia/Baghdad")
# A fixed "now" in UTC used as the anchor for repository window tests.
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

_seq = 0


def _next() -> int:
    global _seq
    _seq += 1
    return _seq


# ── DB helpers ─────────────────────────────────────────────────────────────


async def _make_reservation(
    session,
    *,
    slot_dt: datetime,
    status: ReservationStatus = ReservationStatus.ACTIVE,
    invite_link: str | None = "https://t.me/+abc",
) -> Reservation:
    n = _next()
    channel = Channel(
        name=f"Channel {n}",
        telegram_channel_id=-1000_000_000 - n,
        invite_link=invite_link,
        capacity=100,
        priority=0,
        is_active=True,
    )
    session.add(channel)
    await session.flush()

    user = User(telegram_id=500_000 + n, public_user_code=f"{n:06d}", full_name=f"U{n}")
    session.add(user)
    await session.flush()

    slot = ReservationSlot(slot_datetime=slot_dt, is_booked=True, channel_id=channel.id)
    session.add(slot)
    await session.flush()

    res = Reservation(
        user_id=user.id,
        slot_id=slot.id,
        channel_id=channel.id,
        status=status.value,
    )
    session.add(res)
    await session.flush()
    return res


async def _add_log(
    session,
    *,
    reservation_id: uuid.UUID,
    reminder_type: ReminderType,
    status: DeliveryStatus,
) -> None:
    session.add(
        NotificationLog(
            reservation_id=reservation_id,
            reminder_type=reminder_type.value,
            status=status.value,
        )
    )
    await session.flush()


async def _final_ids(session, from_dt: datetime, to_dt: datetime) -> set[uuid.UUID]:
    repo = NotificationRepository(session)
    rows = await repo.get_reservations_for_window_reminder(
        ReminderType.FINAL, from_dt, to_dt, upper_inclusive=False
    )
    return {r.id for r in rows}


# ── Repository: window ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reservation_inside_final_window_returned(db_session):
    res = await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=2))
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == {res.id}


@pytest.mark.asyncio
async def test_reservation_after_window_excluded(db_session):
    await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=10))
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == set()


@pytest.mark.asyncio
async def test_reservation_before_window_excluded(db_session):
    # Session already started 1 minute ago — before `from_dt`, so never sent.
    await _make_reservation(db_session, slot_dt=NOW - timedelta(minutes=1))
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == set()


@pytest.mark.asyncio
async def test_lower_bound_inclusive_upper_bound_exclusive(db_session):
    at_lower = await _make_reservation(db_session, slot_dt=NOW)
    await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=5))  # at upper
    # [NOW, NOW+5): lower included, upper excluded.
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == {at_lower.id}


@pytest.mark.asyncio
async def test_cancelled_reservation_excluded(db_session):
    await _make_reservation(
        db_session,
        slot_dt=NOW + timedelta(minutes=2),
        status=ReservationStatus.CANCELLED,
    )
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == set()


@pytest.mark.asyncio
async def test_timezone_correctness(db_session):
    # Slot stored as a UTC instant; window expressed in Baghdad (UTC+3). The
    # comparison must be on the underlying instant, not the wall-clock text.
    slot_utc = NOW + timedelta(minutes=2)
    res = await _make_reservation(db_session, slot_dt=slot_utc)
    from_dt = NOW.astimezone(BAGHDAD)
    to_dt = (NOW + timedelta(minutes=5)).astimezone(BAGHDAD)
    assert await _final_ids(db_session, from_dt, to_dt) == {res.id}


# ── Repository: dedup / retry ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sent_log_suppresses_future_sends(db_session):
    res = await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=2))
    await _add_log(
        db_session,
        reservation_id=res.id,
        reminder_type=ReminderType.FINAL,
        status=DeliveryStatus.SENT,
    )
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == set()


@pytest.mark.asyncio
async def test_failed_log_remains_eligible(db_session):
    res = await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=2))
    await _add_log(
        db_session,
        reservation_id=res.id,
        reminder_type=ReminderType.FINAL,
        status=DeliveryStatus.FAILED,
    )
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == {res.id}


@pytest.mark.asyncio
async def test_final_independent_of_pre_session_and_same_day(db_session):
    # A reservation already SENT its pre-session and same-day reminders must
    # still be eligible for the final reminder — types are independent.
    res = await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=2))
    await _add_log(
        db_session,
        reservation_id=res.id,
        reminder_type=ReminderType.PRE_SESSION,
        status=DeliveryStatus.SENT,
    )
    await _add_log(
        db_session,
        reservation_id=res.id,
        reminder_type=ReminderType.SAME_DAY,
        status=DeliveryStatus.SENT,
    )
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == {res.id}


@pytest.mark.asyncio
async def test_retry_roundtrip_upserts_single_row(db_session):
    # FAILED then a successful retry: log() upserts, so exactly one row survives
    # (unique constraint intact, no duplicate delivery), and the second query
    # correctly excludes the now-SENT reservation.
    res = await _make_reservation(db_session, slot_dt=NOW + timedelta(minutes=2))
    repo = NotificationRepository(db_session)

    await repo.log(res.id, ReminderType.FINAL, DeliveryStatus.FAILED, "boom")
    await db_session.flush()
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == {res.id}

    await repo.log(res.id, ReminderType.FINAL, DeliveryStatus.SENT)
    await db_session.flush()
    assert await _final_ids(db_session, NOW, NOW + timedelta(minutes=5)) == set()

    rows = await repo.get_for_reservation(res.id)
    finals = [r for r in rows if r.reminder_type == ReminderType.FINAL.value]
    assert len(finals) == 1
    assert finals[0].status == DeliveryStatus.SENT.value
    assert finals[0].error_message is None


# ── Service: delivery ──────────────────────────────────────────────────────


@pytest.fixture
def svc():
    s = ReminderService.__new__(ReminderService)
    s._notif_repo = AsyncMock()
    s._notif_svc = AsyncMock()
    return s


def _fake_res(*, invite_link: str | None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user=SimpleNamespace(telegram_id=555),
        slot=SimpleNamespace(
            channel=SimpleNamespace(invite_link=invite_link, name="My Channel")
        ),
    )


@pytest.mark.asyncio
async def test_deliver_final_success_logs_sent(svc):
    svc._notif_svc.send = AsyncMock(return_value=(True, None))
    res = _fake_res(invite_link="https://t.me/+abc")

    ok = await svc._deliver_final(res)

    assert ok is True
    svc._notif_svc.send.assert_awaited_once()
    assert svc._notif_svc.send.await_args.args[0] == 555
    log_kwargs = svc._notif_repo.log.await_args.kwargs
    assert log_kwargs["reminder_type"] == ReminderType.FINAL
    assert log_kwargs["status"] == DeliveryStatus.SENT
    assert log_kwargs["reservation_id"] == res.id
    assert log_kwargs["error_message"] is None


@pytest.mark.asyncio
async def test_deliver_final_failure_logs_failed(svc):
    svc._notif_svc.send = AsyncMock(return_value=(False, "chat not found"))
    res = _fake_res(invite_link="https://t.me/+abc")

    ok = await svc._deliver_final(res)

    assert ok is False
    log_kwargs = svc._notif_repo.log.await_args.kwargs
    assert log_kwargs["status"] == DeliveryStatus.FAILED
    assert log_kwargs["error_message"] == "chat not found"


@pytest.mark.asyncio
async def test_deliver_final_includes_invite_link(svc):
    svc._notif_svc.send = AsyncMock(return_value=(True, None))
    res = _fake_res(invite_link="https://t.me/+secret")

    await svc._deliver_final(res)

    text = svc._notif_svc.send.await_args.args[1]
    assert 'href="https://t.me/+secret"' in text
    assert "Join Live Session" in text
    assert "previous invitation" not in text


@pytest.mark.asyncio
async def test_deliver_final_falls_back_when_no_invite_link(svc):
    svc._notif_svc.send = AsyncMock(return_value=(True, None))
    res = _fake_res(invite_link=None)

    await svc._deliver_final(res)

    text = svc._notif_svc.send.await_args.args[1]
    assert "Please open the Telegram channel from your previous invitation." in text
    assert "href=" not in text
    assert "Join Live Session" not in text


@pytest.mark.asyncio
async def test_send_final_reminders_uses_forward_only_window(svc):
    svc._notif_repo.get_reservations_for_window_reminder = AsyncMock(return_value=[])

    await svc.send_final_reminders()

    call = svc._notif_repo.get_reservations_for_window_reminder.await_args
    assert call.args[0] == ReminderType.FINAL
    assert call.kwargs.get("upper_inclusive") is False
    from_dt, to_dt = call.args[1], call.args[2]
    assert to_dt - from_dt == timedelta(minutes=settings.FINAL_REMINDER_MINUTES)


@pytest.mark.asyncio
async def test_send_final_reminders_counts_successful_deliveries(svc):
    r1, r2 = _fake_res(invite_link="x"), _fake_res(invite_link=None)
    svc._notif_repo.get_reservations_for_window_reminder = AsyncMock(return_value=[r1, r2])
    svc._deliver_final = AsyncMock(side_effect=[True, False])

    assert await svc.send_final_reminders() == 1
    assert svc._deliver_final.await_count == 2


# ── Scheduler job wrapper ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_disabled_is_noop():
    from app.schedulers.jobs import reminders as job_mod

    with patch.object(job_mod.settings, "FINAL_REMINDER_ENABLED", False), \
         patch.object(job_mod.redis_client, "set_nx", AsyncMock()) as set_nx, \
         patch.object(job_mod, "ReminderService") as svc_cls:
        await job_mod.send_final_reminders_job()

    set_nx.assert_not_called()
    svc_cls.assert_not_called()


@pytest.mark.asyncio
async def test_job_skips_when_lock_held():
    from app.schedulers.jobs import reminders as job_mod

    with patch.object(job_mod.settings, "FINAL_REMINDER_ENABLED", True), \
         patch.object(job_mod.redis_client, "set_nx", AsyncMock(return_value=False)), \
         patch.object(job_mod, "ReminderService") as svc_cls:
        await job_mod.send_final_reminders_job()

    svc_cls.assert_not_called()


@pytest.mark.asyncio
async def test_job_invokes_service_and_releases_lock():
    from app.schedulers.jobs import reminders as job_mod

    service = MagicMock()
    service.send_final_reminders = AsyncMock(return_value=3)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(job_mod.settings, "FINAL_REMINDER_ENABLED", True), \
         patch.object(job_mod.redis_client, "set_nx", AsyncMock(return_value=True)), \
         patch.object(job_mod.redis_client, "delete", AsyncMock()) as delete, \
         patch.object(job_mod, "AsyncSessionFactory", return_value=cm), \
         patch.object(job_mod, "ReminderService", return_value=service), \
         patch.object(job_mod, "get_bot", return_value=MagicMock()):
        await job_mod.send_final_reminders_job()

    service.send_final_reminders.assert_awaited_once()
    delete.assert_awaited_once()
