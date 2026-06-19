"""API tests for POST /api/admin/reservations/{id}/cancel — mocked, no DB.

The service/repository layers are patched out so these tests exercise only the
HTTP contract: status codes, response shape, auth dependency, and that the admin
audit log is written on success.
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
from app.core.exceptions import NotFoundError, ReservationNotCancellableError
from app.db.session import get_db_session


def _make_fake_res(status: str = "cancelled"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        notes=None,
        slot=SimpleNamespace(
            id=uuid.uuid4(),
            slot_datetime=datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc),
        ),
        channel=SimpleNamespace(id=uuid.uuid4(), name="Channel 1"),
        user=SimpleNamespace(
            id=uuid.uuid4(),
            public_user_code="ABC123",
            full_name="Test User",
            gender="male",
            country_rel=None,
            participation_score=3,
        ),
    )


@pytest_asyncio.fixture
async def client(monkeypatch):
    app = create_app()

    # ── Auth + DB session: bypass real auth and DB ────────────────────────────
    app.dependency_overrides[get_current_admin] = lambda: "admin"

    async def _fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _fake_session

    # Audit repo — capture the .log() call.
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
    svc.admin_cancel_reservation = AsyncMock(
        return_value=return_value, side_effect=side_effect
    )
    monkeypatch.setattr(res_mod, "ReservationService", MagicMock(return_value=svc))
    return svc


@pytest.mark.asyncio
async def test_cancel_success_returns_detail_and_audits(client, monkeypatch):
    fake = _make_fake_res(status="cancelled")
    _patch_service(monkeypatch, return_value=fake)
    monkeypatch.setattr(
        res_mod,
        "ReservationRepository",
        MagicMock(return_value=MagicMock(
            get_reservation_admin_detail=AsyncMock(return_value=fake)
        )),
    )

    resp = await client.post(
        f"/api/admin/reservations/{fake.id}/cancel", json={"reason": "duplicate"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(fake.id)
    assert body["status"] == "cancelled"

    # Audit entry written with the correct action/entity.
    client._audit_log.assert_awaited_once()
    kwargs = client._audit_log.await_args.kwargs
    assert kwargs["action"] == "reservation_cancelled_by_admin"
    assert kwargs["entity_type"] == "reservation"
    assert kwargs["entity_id"] == str(fake.id)
    assert kwargs["admin_username"] == "admin"


@pytest.mark.asyncio
async def test_cancel_not_found_returns_404(client, monkeypatch):
    rid = uuid.uuid4()
    _patch_service(monkeypatch, side_effect=NotFoundError("Reservation"))

    resp = await client.post(f"/api/admin/reservations/{rid}/cancel", json={})

    assert resp.status_code == 404
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_already_cancelled_returns_409(client, monkeypatch):
    rid = uuid.uuid4()
    _patch_service(
        monkeypatch, side_effect=ReservationNotCancellableError("cancelled")
    )

    resp = await client.post(f"/api/admin/reservations/{rid}/cancel", json={})

    assert resp.status_code == 409
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_reason_too_long_returns_422(client, monkeypatch):
    rid = uuid.uuid4()
    _patch_service(monkeypatch, return_value=_make_fake_res())

    resp = await client.post(
        f"/api/admin/reservations/{rid}/cancel", json={"reason": "x" * 257}
    )

    assert resp.status_code == 422
