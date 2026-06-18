"""Unit tests for UserBroadcastService — mocked bot, repos, and session.

These exercise the delivery state machine (success / blocked / failure) and the
creation/snapshot path without touching a database or sleeping.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from app.db.models.user_broadcast import UserBroadcastStatus
from app.services.user_broadcast import UserBroadcastService


def _recipient(tg_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), telegram_id=tg_id, status="pending")


def _broadcast(**kw) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        status=UserBroadcastStatus.PENDING.value,
        parse_mode="HTML",
        message="hello",
        total_recipients=0,
        success_count=0,
        failed_count=0,
        blocked_count=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def service():
    svc = UserBroadcastService.__new__(UserBroadcastService)
    svc._session = AsyncMock()
    svc._bot = AsyncMock()
    svc._segmentation = AsyncMock()
    svc._broadcast_repo = AsyncMock()
    svc._recipient_repo = AsyncMock()
    svc._user_repo = AsyncMock()
    return svc


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("app.services.user_broadcast.asyncio.sleep", new=AsyncMock()):
        yield


# ── Delivery: success ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delivery_all_success(service):
    bc = _broadcast(total_recipients=2)
    service._broadcast_repo.get_by_id = AsyncMock(return_value=bc)
    service._recipient_repo.get_pending = AsyncMock(return_value=[_recipient(1), _recipient(2)])

    await service.run_broadcast(bc.id)

    assert service._recipient_repo.mark_sent.await_count == 2
    service._broadcast_repo.mark_finished.assert_awaited_once()
    kwargs = service._broadcast_repo.mark_finished.await_args.kwargs
    assert kwargs["status"] == UserBroadcastStatus.COMPLETED
    assert kwargs["success_count"] == 2
    assert kwargs["failed_count"] == 0
    assert kwargs["blocked_count"] == 0


# ── Delivery: blocked user ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delivery_blocked_user_flagged(service):
    bc = _broadcast(total_recipients=2)
    r_ok, r_blocked = _recipient(1), _recipient(2)
    service._broadcast_repo.get_by_id = AsyncMock(return_value=bc)
    service._recipient_repo.get_pending = AsyncMock(return_value=[r_ok, r_blocked])

    async def send(chat_id, **_):
        if chat_id == 2:
            raise TelegramForbiddenError(method=None, message="bot was blocked by the user")
        return SimpleNamespace(message_id=1)

    service._bot.send_message = AsyncMock(side_effect=send)

    await service.run_broadcast(bc.id)

    service._recipient_repo.mark_blocked.assert_awaited_once()
    service._user_repo.mark_bot_blocked.assert_awaited_once_with(r_blocked.user_id)
    kwargs = service._broadcast_repo.mark_finished.await_args.kwargs
    assert kwargs["success_count"] == 1
    assert kwargs["blocked_count"] == 1
    assert kwargs["failed_count"] == 0
    assert kwargs["status"] == UserBroadcastStatus.COMPLETED


# ── Delivery: telegram failure ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delivery_failure_continues(service):
    bc = _broadcast(total_recipients=2)
    r_fail, r_ok = _recipient(1), _recipient(2)
    service._broadcast_repo.get_by_id = AsyncMock(return_value=bc)
    service._recipient_repo.get_pending = AsyncMock(return_value=[r_fail, r_ok])

    async def send(chat_id, **_):
        if chat_id == 1:
            raise TelegramAPIError(method=None, message="chat not found")
        return SimpleNamespace(message_id=1)

    service._bot.send_message = AsyncMock(side_effect=send)

    await service.run_broadcast(bc.id)

    service._recipient_repo.mark_failed.assert_awaited_once()
    service._recipient_repo.mark_sent.assert_awaited_once()  # the run did not stop
    kwargs = service._broadcast_repo.mark_finished.await_args.kwargs
    assert kwargs["success_count"] == 1
    assert kwargs["failed_count"] == 1
    assert kwargs["blocked_count"] == 0


# ── Guard: non-runnable status ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_completed_broadcast_not_rerun(service):
    bc = _broadcast(status=UserBroadcastStatus.COMPLETED.value)
    service._broadcast_repo.get_by_id = AsyncMock(return_value=bc)

    await service.run_broadcast(bc.id)

    service._broadcast_repo.mark_processing.assert_not_awaited()
    service._recipient_repo.get_pending.assert_not_awaited()


# ── Creation / snapshot ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_broadcast_snapshots_audience(service):
    from app.services.segmentation import SegmentFilter

    recipients = [(uuid.uuid4(), 1), (uuid.uuid4(), 2), (uuid.uuid4(), 3)]
    service._segmentation.fetch_recipients = AsyncMock(return_value=recipients)
    created = _broadcast(total_recipients=3)
    service._broadcast_repo.create = AsyncMock(return_value=created)
    service._recipient_repo.bulk_create = AsyncMock(return_value=3)

    result = await service.create_broadcast(
        message="hi",
        parse_mode="HTML",
        audience_type="all_users",
        segment_filter=SegmentFilter(),
        filters_payload=None,
        created_by="admin",
    )

    assert result is created
    create_kwargs = service._broadcast_repo.create.await_args.kwargs
    assert create_kwargs["total_recipients"] == 3
    service._recipient_repo.bulk_create.assert_awaited_once_with(created.id, recipients)
    service._session.commit.assert_awaited()


# ── Progress percent helper ──────────────────────────────────────────────────

def test_progress_percent():
    from app.api.admin.broadcast import _progress_percent

    assert _progress_percent(SimpleNamespace(
        total_recipients=0, success_count=0, failed_count=0, blocked_count=0, status="completed"
    )) == 100
    assert _progress_percent(SimpleNamespace(
        total_recipients=0, success_count=0, failed_count=0, blocked_count=0, status="pending"
    )) == 0
    assert _progress_percent(SimpleNamespace(
        total_recipients=200, success_count=100, failed_count=20, blocked_count=10, status="processing"
    )) == 65
    assert _progress_percent(SimpleNamespace(
        total_recipients=5000, success_count=3120, failed_count=42, blocked_count=130, status="processing"
    )) == 66
