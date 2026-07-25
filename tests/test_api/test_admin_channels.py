"""API tests for /api/admin/channels — CRUD, reorder, deletion safety.

Mirrors tests/test_api/test_admin_create.py's approach: the repository layer
is patched out so these tests exercise only the HTTP contract (status codes,
validation, response shape, audit logging) without needing a real database.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

import app.api.admin.channels as channels_mod
from app.api.admin.deps import get_current_admin
from app.api.main import create_app
from app.db.session import get_db_session


def _make_channel(
    *,
    name="Echoes",
    telegram_channel_id=-1001000000001,
    invite_link="https://t.me/+abc",
    priority=0,
    is_active=True,
):
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        telegram_channel_id=telegram_channel_id,
        invite_link=invite_link,
        priority=priority,
        is_active=is_active,
        created_at=now,
        updated_at=now,
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
        channels_mod,
        "AdminAuditLogRepository",
        MagicMock(return_value=MagicMock(log=audit_log)),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._audit_log = audit_log  # type: ignore[attr-defined]
        yield c

    app.dependency_overrides.clear()


def _patch_repo(monkeypatch, **methods):
    repo = MagicMock()
    for name, value in methods.items():
        setattr(repo, name, value)
    monkeypatch.setattr(channels_mod, "ChannelRepository", MagicMock(return_value=repo))
    return repo


# ── List / Get ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_channels_returns_ordered_list(client, monkeypatch):
    chans = [_make_channel(name="A", priority=0), _make_channel(name="B", priority=1)]
    _patch_repo(monkeypatch, get_all_channels=AsyncMock(return_value=chans))

    resp = await client.get("/api/admin/channels")

    assert resp.status_code == 200
    body = resp.json()
    assert [c["name"] for c in body] == ["A", "B"]


@pytest.mark.asyncio
async def test_get_channel_not_found_returns_404(client, monkeypatch):
    _patch_repo(monkeypatch, get_by_id=AsyncMock(return_value=None))

    resp = await client.get(f"/api/admin/channels/{uuid.uuid4()}")

    assert resp.status_code == 404


# ── Create ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_success_returns_201_and_audits(client, monkeypatch):
    created = _make_channel(name="New Channel", priority=3)
    repo = _patch_repo(
        monkeypatch,
        get_max_priority=AsyncMock(return_value=2),
        save=AsyncMock(return_value=created),
    )

    resp = await client.post(
        "/api/admin/channels",
        json={
            "name": "New Channel",
            "telegram_channel_id": -1009999999999,
            "invite_link": "https://t.me/+new",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["name"] == "New Channel"
    repo.save.assert_awaited_once()
    client._audit_log.assert_awaited_once()
    assert client._audit_log.await_args.kwargs["action"] == "channel_created"


@pytest.mark.asyncio
async def test_create_duplicate_telegram_id_returns_422(client, monkeypatch):
    _patch_repo(
        monkeypatch,
        get_max_priority=AsyncMock(return_value=0),
        save=AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup"))),
    )

    resp = await client.post(
        "/api/admin/channels",
        json={"name": "Dup", "telegram_channel_id": -100111},
    )

    assert resp.status_code == 422
    assert "already exists" in resp.json()["detail"]
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_positive_telegram_id_rejected(client, monkeypatch):
    _patch_repo(monkeypatch)

    resp = await client.post(
        "/api/admin/channels",
        json={"name": "Bad", "telegram_channel_id": 100111},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_empty_name_rejected(client, monkeypatch):
    _patch_repo(monkeypatch)

    resp = await client.post(
        "/api/admin/channels",
        json={"name": "", "telegram_channel_id": -100111},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_bad_invite_link_rejected(client, monkeypatch):
    _patch_repo(monkeypatch)

    resp = await client.post(
        "/api/admin/channels",
        json={
            "name": "Bad Link",
            "telegram_channel_id": -100111,
            "invite_link": "http://example.com/not-telegram",
        },
    )

    assert resp.status_code == 422


# ── Update ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_channel_patches_fields_and_audits(client, monkeypatch):
    existing = _make_channel(name="Old")
    updated = _make_channel(name="Renamed")
    repo = _patch_repo(
        monkeypatch,
        get_by_id=AsyncMock(return_value=existing),
        save=AsyncMock(return_value=updated),
    )

    resp = await client.patch(
        f"/api/admin/channels/{existing.id}", json={"name": "Renamed"}
    )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    repo.save.assert_awaited_once()
    assert client._audit_log.await_args.kwargs["action"] == "channel_updated"


@pytest.mark.asyncio
async def test_update_channel_not_found_returns_404(client, monkeypatch):
    _patch_repo(monkeypatch, get_by_id=AsyncMock(return_value=None))

    resp = await client.patch(f"/api/admin/channels/{uuid.uuid4()}", json={"name": "X"})

    assert resp.status_code == 404


# ── Delete ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_blocked_when_slots_exist(client, monkeypatch):
    existing = _make_channel()
    repo = _patch_repo(
        monkeypatch,
        get_by_id=AsyncMock(return_value=existing),
        has_any_slots_or_reservations=AsyncMock(return_value=True),
        delete=AsyncMock(),
    )

    resp = await client.delete(f"/api/admin/channels/{existing.id}")

    assert resp.status_code == 422
    assert "Disable it instead" in resp.json()["detail"]
    repo.delete.assert_not_awaited()
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_succeeds_when_no_dependencies(client, monkeypatch):
    existing = _make_channel()
    repo = _patch_repo(
        monkeypatch,
        get_by_id=AsyncMock(return_value=existing),
        has_any_slots_or_reservations=AsyncMock(return_value=False),
        delete=AsyncMock(),
    )

    resp = await client.delete(f"/api/admin/channels/{existing.id}")

    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    repo.delete.assert_awaited_once()
    assert client._audit_log.await_args.kwargs["action"] == "channel_deleted"


# ── Reorder ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reorder_swaps_priority_with_neighbor(client, monkeypatch):
    channel = _make_channel(name="Mover", priority=2)
    neighbor = _make_channel(name="Neighbor", priority=1)

    async def _fake_save(instance):
        return instance

    repo = _patch_repo(
        monkeypatch,
        get_by_id=AsyncMock(return_value=channel),
        get_neighbor=AsyncMock(return_value=neighbor),
        save=AsyncMock(side_effect=_fake_save),
    )

    resp = await client.post(
        f"/api/admin/channels/{channel.id}/reorder", json={"direction": "up"}
    )

    assert resp.status_code == 200
    assert channel.priority == 1
    assert neighbor.priority == 2
    assert repo.save.await_count == 2
    assert client._audit_log.await_args.kwargs["action"] == "channel_reordered"


@pytest.mark.asyncio
async def test_reorder_at_boundary_is_noop(client, monkeypatch):
    channel = _make_channel(name="Top", priority=0)
    repo = _patch_repo(
        monkeypatch,
        get_by_id=AsyncMock(return_value=channel),
        get_neighbor=AsyncMock(return_value=None),
        save=AsyncMock(),
    )

    resp = await client.post(
        f"/api/admin/channels/{channel.id}/reorder", json={"direction": "up"}
    )

    assert resp.status_code == 200
    repo.save.assert_not_awaited()
    client._audit_log.assert_not_awaited()
