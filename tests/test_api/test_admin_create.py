"""API tests for POST /api/admin/reservations and GET /available-slots — mocked.

The service/repository layers are patched out so these tests exercise only the
HTTP contract: status codes, response shape, the booking-error → HTTP mapping,
and that the admin audit log is written on success (and only on success).
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.api.admin.reservations as res_mod
from app.api.admin.deps import get_current_admin
from app.api.main import create_app
from app.core.exceptions import (
    DailyLimitError,
    NotFoundError,
    SlotUnavailableError,
    UserBannedError,
)
from app.db.session import get_db_session


def _make_fake_res(status: str = "active"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        notes=None,
        slot=SimpleNamespace(
            id=uuid.uuid4(),
            slot_datetime=datetime(2026, 6, 25, 18, 0, tzinfo=timezone.utc),
        ),
        channel=SimpleNamespace(id=uuid.uuid4(), name="Channel 1"),
        user=SimpleNamespace(
            id=uuid.uuid4(),
            public_user_code="ABC123",
            full_name="Test User",
            gender="male",
            country_rel=None,
            participation_score=4,
        ),
    )


@pytest_asyncio.fixture
async def client(monkeypatch):
    app = create_app()

    app.dependency_overrides[get_current_admin] = lambda: "admin"

    async def _fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _fake_session

    audit_log = AsyncMock()
    monkeypatch.setattr(
        res_mod,
        "AdminAuditLogRepository",
        MagicMock(return_value=MagicMock(log=audit_log)),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._audit_log = audit_log  # type: ignore[attr-defined]
        yield c

    app.dependency_overrides.clear()


def _patch_service(monkeypatch, *, return_value=None, side_effect=None):
    svc = MagicMock()
    svc.admin_create_reservation = AsyncMock(
        return_value=return_value, side_effect=side_effect
    )
    monkeypatch.setattr(res_mod, "ReservationService", MagicMock(return_value=svc))
    return svc


def _body(user_id=None, slot_id=None):
    return {
        "user_id": str(user_id or uuid.uuid4()),
        "slot_id": str(slot_id or uuid.uuid4()),
    }


@pytest.mark.asyncio
async def test_create_success_returns_201_detail_and_audits(client, monkeypatch):
    fake = _make_fake_res()
    _patch_service(monkeypatch, return_value=fake)
    monkeypatch.setattr(
        res_mod,
        "ReservationRepository",
        MagicMock(return_value=MagicMock(
            get_reservation_admin_detail=AsyncMock(return_value=fake)
        )),
    )

    resp = await client.post("/api/admin/reservations", json=_body())

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(fake.id)
    assert body["status"] == "active"
    assert body["user"]["public_user_code"] == "ABC123"

    client._audit_log.assert_awaited_once()
    kwargs = client._audit_log.await_args.kwargs
    assert kwargs["action"] == "reservation_created_by_admin"
    assert kwargs["entity_type"] == "reservation"
    assert kwargs["entity_id"] == str(fake.id)
    assert kwargs["admin_username"] == "admin"


@pytest.mark.asyncio
async def test_create_user_not_found_returns_404(client, monkeypatch):
    _patch_service(monkeypatch, side_effect=NotFoundError("User"))

    resp = await client.post("/api/admin/reservations", json=_body())

    assert resp.status_code == 404
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_banned_user_returns_422(client, monkeypatch):
    _patch_service(monkeypatch, side_effect=UserBannedError())

    resp = await client.post("/api/admin/reservations", json=_body())

    assert resp.status_code == 422
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_daily_limit_returns_409(client, monkeypatch):
    _patch_service(monkeypatch, side_effect=DailyLimitError())

    resp = await client.post("/api/admin/reservations", json=_body())

    assert resp.status_code == 409
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_slot_unavailable_returns_409(client, monkeypatch):
    _patch_service(monkeypatch, side_effect=SlotUnavailableError())

    resp = await client.post("/api/admin/reservations", json=_body())

    assert resp.status_code == 409
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_invalid_uuid_returns_422(client, monkeypatch):
    _patch_service(monkeypatch)

    resp = await client.post(
        "/api/admin/reservations", json={"user_id": "not-a-uuid", "slot_id": "x"}
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_available_slots_returns_slot_list(client, monkeypatch):
    slot = SimpleNamespace(
        id=uuid.uuid4(),
        slot_datetime=datetime(2026, 6, 25, 18, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        res_mod,
        "SlotRepository",
        MagicMock(return_value=MagicMock(
            get_available_slots_for_date_and_channel=AsyncMock(return_value=[slot])
        )),
    )

    resp = await client.get(
        "/api/admin/reservations/available-slots",
        params={"channel_id": str(uuid.uuid4()), "date": "2026-06-25"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(slot.id)
    assert "slot_time_local" in body[0]
