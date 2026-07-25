"""API tests for GET /api/admin/reservations/{id}/timeline — mocked, no DB.

Exercises only the HTTP contract: status codes, response shape, auth, and that
the service's NotFoundError is translated to a 404.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.api.admin.reservations as res_mod
from app.api.admin.deps import get_current_admin
from app.api.main import create_app
from app.core.exceptions import NotFoundError
from app.db.session import get_db_session
from app.services.reservation_timeline import TimelineEvent


@pytest_asyncio.fixture
async def client():
    app = create_app()
    app.dependency_overrides[get_current_admin] = lambda: "admin"

    async def _fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _fake_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


def _patch_service(monkeypatch, *, return_value=None, side_effect=None):
    svc = MagicMock()
    svc.build = AsyncMock(return_value=return_value, side_effect=side_effect)
    monkeypatch.setattr(
        res_mod, "ReservationTimelineService", MagicMock(return_value=svc)
    )
    return svc


@pytest.mark.asyncio
async def test_timeline_success_returns_sorted_events(client, monkeypatch):
    rid = uuid.uuid4()
    events = [
        TimelineEvent(
            type="reservation_created",
            title="Reservation Created",
            timestamp=datetime(2026, 6, 19, 15, 30, tzinfo=timezone.utc),
            metadata={"created_by_admin": False},
        ),
        TimelineEvent(
            type="score_awarded",
            title="Score +1 Awarded",
            timestamp=datetime(2026, 6, 19, 15, 30, tzinfo=timezone.utc),
            metadata={"delta": 1},
        ),
    ]
    _patch_service(monkeypatch, return_value=events)

    resp = await client.get(f"/api/admin/reservations/{rid}/timeline")

    assert resp.status_code == 200
    body = resp.json()
    assert [e["type"] for e in body] == ["reservation_created", "score_awarded"]
    assert body[1]["title"] == "Score +1 Awarded"
    assert body[0]["metadata"] == {"created_by_admin": False}


@pytest.mark.asyncio
async def test_timeline_empty_returns_empty_array(client, monkeypatch):
    rid = uuid.uuid4()
    _patch_service(monkeypatch, return_value=[])

    resp = await client.get(f"/api/admin/reservations/{rid}/timeline")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_timeline_not_found_returns_404(client, monkeypatch):
    rid = uuid.uuid4()
    _patch_service(monkeypatch, side_effect=NotFoundError("Reservation"))

    resp = await client.get(f"/api/admin/reservations/{rid}/timeline")

    assert resp.status_code == 404
