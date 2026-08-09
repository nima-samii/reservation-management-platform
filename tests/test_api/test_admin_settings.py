"""API tests for the metadata-driven Admin Settings registry — mocked.

Redis is mocked (history/cache invalidation) and the override file is
redirected to a tmp_path so tests never touch the real
data/admin_settings_override.json. `settings` is a process-wide mutable
singleton that PATCH endpoints mutate in place, so an autouse fixture
snapshots/restores every registry-tracked field around each test.
"""
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

import app.api.admin.settings as settings_mod
from app.api.admin.deps import get_current_admin
from app.api.main import create_app
from app.core.config import (
    DEFAULT_RESERVATION_STRATEGY,
    MAX_REQUIRED_CHANNELS,
    RESERVATION_STRATEGIES,
    load_settings_override,
    save_settings_override,
    settings,
)
from app.core.settings_registry import CATEGORIES, SETTINGS_REGISTRY, RestartBehavior

SECRET_KEYS = {
    "BOT_TOKEN", "WEBHOOK_URL", "WEBHOOK_PATH", "WEBHOOK_SECRET",
    "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD",
    "APP_HOST", "APP_PORT", "ENVIRONMENT", "DEBUG", "TIMEZONE",
    "LOG_LEVEL", "LOG_FORMAT", "ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_JWT_SECRET", "ADMIN_IDS",
}


@pytest.fixture(autouse=True)
def _restore_settings():
    tracked_keys = [m.key for m in SETTINGS_REGISTRY] + [
        f"REQUIRED_CHANNEL_{i}_{suffix}"
        for i in range(1, MAX_REQUIRED_CHANNELS + 1)
        for suffix in ("ID", "URL")
    ]
    snapshot = {k: getattr(settings, k) for k in tracked_keys}
    yield
    for k, v in snapshot.items():
        object.__setattr__(settings, k, v)


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    app = create_app()
    app.dependency_overrides[get_current_admin] = lambda: "admin"

    fake_redis = MagicMock()
    fake_redis.lpush = AsyncMock()
    fake_redis.ltrim = AsyncMock()
    fake_redis.lrange = AsyncMock(return_value=[])
    fake_redis.delete = AsyncMock()
    monkeypatch.setattr(settings_mod, "redis_client", fake_redis)
    monkeypatch.setattr(
        "app.core.config.SETTINGS_OVERRIDE_PATH", tmp_path / "admin_settings_override.json"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._fake_redis = fake_redis  # type: ignore[attr-defined]
        yield c

    app.dependency_overrides.clear()


# ── Metadata ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metadata_includes_all_categories_and_excludes_secrets(client):
    resp = await client.get("/api/admin/settings/metadata")
    assert resp.status_code == 200
    body = resp.json()

    returned_slugs = {c["key"] for c in body}
    expected_slugs = {slug for slug, _ in CATEGORIES}
    assert returned_slugs == expected_slugs

    all_field_keys = {f["key"] for c in body for f in c["fields"]}
    for secret in SECRET_KEYS:
        assert secret.lower() not in all_field_keys
        assert secret not in all_field_keys


@pytest.mark.asyncio
async def test_restart_behavior_metadata(client):
    resp = await client.get("/api/admin/settings/metadata")
    fields_by_key = {
        f["key"]: f for c in resp.json() for f in c["fields"]
    }
    # These three are hour-based scheduler jobs, but the PATCH handler now
    # reschedules them in place via apply_scheduler_setting_changes(), so they
    # apply live rather than requiring a process restart.
    for key in ("same_day_reminder_hour", "daily_broadcast_hour", "inactivity_reminder_hour"):
        assert fields_by_key[key]["restart_behavior"] == RestartBehavior.LIVE.value
    assert fields_by_key["membership_cache_ttl"]["restart_behavior"] == RestartBehavior.CACHE_REFRESH.value
    assert fields_by_key["max_active_reservations"]["restart_behavior"] == RestartBehavior.LIVE.value


# ── GET / PATCH scalar settings ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_settings_returns_new_field(client):
    resp = await client.get("/api/admin/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rate_limits"]["rate_limit_requests"] == settings.RATE_LIMIT_REQUESTS
    assert "score_notifications" in body
    assert "inactivity_reminder" in body


@pytest.mark.asyncio
async def test_patch_unknown_category_422(client):
    resp = await client.patch("/api/admin/settings", json={"not_a_category": {"x": 1}})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_unknown_field_422(client):
    resp = await client.patch(
        "/api/admin/settings", json={"rate_limits": {"not_a_field": 1}}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_out_of_range_int_422(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"reservation_rules": {"max_active_reservations": 999}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_malformed_final_slot_time_422(client):
    resp = await client.patch(
        "/api/admin/settings", json={"slot_schedule": {"final_slot_time": "25:99"}}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_slot_start_end_cross_field_422(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"slot_schedule": {"slot_start_hour": 20, "slot_end_hour": 18}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_valid_change_persists_and_roundtrips(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"rate_limits": {"rate_limit_requests": 45}},
    )
    assert resp.status_code == 200
    assert resp.json()["rate_limits"]["rate_limit_requests"] == 45

    resp2 = await client.get("/api/admin/settings")
    assert resp2.json()["rate_limits"]["rate_limit_requests"] == 45
    assert settings.RATE_LIMIT_REQUESTS == 45


@pytest.mark.asyncio
async def test_patch_broadcast_hour_reschedules_running_job(client, monkeypatch):
    """Changing a scheduler hour reschedules the live job (no restart needed)."""
    fake_scheduler = MagicMock()
    monkeypatch.setattr(
        "app.schedulers.setup.get_scheduler", lambda: fake_scheduler
    )

    resp = await client.patch(
        "/api/admin/settings", json={"broadcast": {"daily_broadcast_hour": "14:30"}}
    )
    assert resp.status_code == 200
    assert settings.DAILY_BROADCAST_HOUR == "14:30"

    # The daily_broadcast job was rescheduled with the new time (hour + minute).
    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert "daily_broadcast" in args
    assert str(kwargs["trigger"]) == "cron[hour='14', minute='30']"


@pytest.mark.asyncio
async def test_patch_cutoff_time_minute_precision_roundtrips(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"reservation_rules": {"same_day_cutoff_hour": "14:15"}},
    )
    assert resp.status_code == 200
    assert resp.json()["reservation_rules"]["same_day_cutoff_hour"] == "14:15"
    assert settings.SAME_DAY_CUTOFF_HOUR == "14:15"


@pytest.mark.asyncio
async def test_patch_invalid_time_rejected(client):
    resp = await client.patch(
        "/api/admin/settings", json={"broadcast": {"daily_broadcast_hour": "25:99"}}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_non_scheduler_setting_does_not_reschedule(client, monkeypatch):
    """A live (non-scheduler) setting must not touch the scheduler."""
    fake_scheduler = MagicMock()
    monkeypatch.setattr(
        "app.schedulers.setup.get_scheduler", lambda: fake_scheduler
    )

    resp = await client.patch(
        "/api/admin/settings", json={"rate_limits": {"rate_limit_requests": 33}}
    )
    assert resp.status_code == 200
    fake_scheduler.reschedule_job.assert_not_called()


# ── Reservation strategy (Phase 1: configuration only) ────────────────────


def test_reservation_strategy_defaults_to_threshold_unlock():
    """The historical behaviour must remain the default — adding the setting
    must not change how any existing deployment allocates reservations."""
    assert DEFAULT_RESERVATION_STRATEGY == "THRESHOLD_UNLOCK"
    assert settings.RESERVATION_STRATEGY == "THRESHOLD_UNLOCK"


@pytest.mark.asyncio
async def test_metadata_exposes_strategy_as_select_with_choices(client):
    resp = await client.get("/api/admin/settings/metadata")
    fields_by_key = {f["key"]: f for c in resp.json() for f in c["fields"]}

    field = fields_by_key["reservation_strategy"]
    assert field["widget"] == "select"
    assert field["restart_behavior"] == RestartBehavior.LIVE.value
    # The dropdown must offer exactly what the validator accepts — no more, no less.
    assert [c["value"] for c in field["choices"]] == list(RESERVATION_STRATEGIES)
    assert all(c["label"] for c in field["choices"])


@pytest.mark.asyncio
async def test_metadata_choices_absent_for_non_select_fields(client):
    resp = await client.get("/api/admin/settings/metadata")
    fields_by_key = {f["key"]: f for c in resp.json() for f in c["fields"]}
    assert fields_by_key["max_active_reservations"]["choices"] is None


@pytest.mark.asyncio
async def test_get_settings_includes_strategy(client):
    resp = await client.get("/api/admin/settings")
    assert resp.json()["reservation_rules"]["reservation_strategy"] == "THRESHOLD_UNLOCK"


@pytest.mark.asyncio
async def test_patch_strategy_to_sequential_fill_roundtrips(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"reservation_rules": {"reservation_strategy": "SEQUENTIAL_FILL"}},
    )
    assert resp.status_code == 200
    assert resp.json()["reservation_rules"]["reservation_strategy"] == "SEQUENTIAL_FILL"

    resp2 = await client.get("/api/admin/settings")
    assert resp2.json()["reservation_rules"]["reservation_strategy"] == "SEQUENTIAL_FILL"
    assert settings.RESERVATION_STRATEGY == "SEQUENTIAL_FILL"


@pytest.mark.asyncio
async def test_patch_strategy_is_case_insensitive_and_canonicalized(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"reservation_rules": {"reservation_strategy": "  sequential_fill  "}},
    )
    assert resp.status_code == 200
    assert settings.RESERVATION_STRATEGY == "SEQUENTIAL_FILL"


@pytest.mark.asyncio
async def test_patch_unknown_strategy_422(client):
    resp = await client.patch(
        "/api/admin/settings",
        json={"reservation_rules": {"reservation_strategy": "ROUND_ROBIN"}},
    )
    assert resp.status_code == 422
    assert settings.RESERVATION_STRATEGY == "THRESHOLD_UNLOCK"


@pytest.mark.asyncio
async def test_patch_strategy_does_not_touch_threshold(client):
    """The two settings are independent — switching strategy must not rewrite
    CHANNEL_CAPACITY_THRESHOLD, so switching back restores the old behaviour."""
    before = settings.CHANNEL_CAPACITY_THRESHOLD
    resp = await client.patch(
        "/api/admin/settings",
        json={"reservation_rules": {"reservation_strategy": "SEQUENTIAL_FILL"}},
    )
    assert resp.status_code == 200
    assert settings.CHANNEL_CAPACITY_THRESHOLD == before


def test_load_settings_override_applies_valid_strategy(tmp_path, monkeypatch):
    override_path = tmp_path / "admin_settings_override.json"
    override_path.write_text(
        json.dumps({"RESERVATION_STRATEGY": "SEQUENTIAL_FILL"}), encoding="utf-8"
    )
    monkeypatch.setattr("app.core.config.SETTINGS_OVERRIDE_PATH", override_path)

    load_settings_override()

    assert settings.RESERVATION_STRATEGY == "SEQUENTIAL_FILL"


def test_load_settings_override_rejects_unknown_strategy(tmp_path, monkeypatch):
    """object.__setattr__ bypasses the pydantic validator, so a hand-edited or
    corrupt override must not be able to install a strategy no resolver knows —
    and must not take the rest of the file down with it."""
    override_path = tmp_path / "admin_settings_override.json"
    override_path.write_text(
        json.dumps(
            {"RESERVATION_STRATEGY": "NONSENSE", "RATE_LIMIT_WINDOW_SECONDS": 88}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.SETTINGS_OVERRIDE_PATH", override_path)

    load_settings_override()

    assert settings.RESERVATION_STRATEGY == "THRESHOLD_UNLOCK"
    assert settings.RATE_LIMIT_WINDOW_SECONDS == 88


# ── Membership channels ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_membership_channels_valid_add_reorder_remove_roundtrip(client):
    resp = await client.put(
        "/api/admin/settings/membership-channels",
        json={
            "channels": [
                {"id": -1001111111111, "url": "https://t.me/one"},
                {"id": -1002222222222, "url": "https://t.me/two"},
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json() == [
        {"id": -1001111111111, "url": "https://t.me/one"},
        {"id": -1002222222222, "url": "https://t.me/two"},
    ]

    get_resp = await client.get("/api/admin/settings/membership-channels")
    assert get_resp.json() == [
        {"id": -1001111111111, "url": "https://t.me/one"},
        {"id": -1002222222222, "url": "https://t.me/two"},
    ]

    # Reorder
    reorder_resp = await client.put(
        "/api/admin/settings/membership-channels",
        json={
            "channels": [
                {"id": -1002222222222, "url": "https://t.me/two"},
                {"id": -1001111111111, "url": "https://t.me/one"},
            ]
        },
    )
    assert reorder_resp.json()[0]["id"] == -1002222222222


@pytest.mark.asyncio
async def test_membership_channels_remove_clears_slot(client):
    await client.put(
        "/api/admin/settings/membership-channels",
        json={
            "channels": [
                {"id": -1001111111111, "url": "https://t.me/one"},
                {"id": -1002222222222, "url": "https://t.me/two"},
                {"id": -1003333333333, "url": "https://t.me/three"},
            ]
        },
    )
    assert settings.REQUIRED_CHANNEL_3_ID == -1003333333333

    await client.put(
        "/api/admin/settings/membership-channels",
        json={"channels": [{"id": -1001111111111, "url": "https://t.me/one"}]},
    )
    assert settings.REQUIRED_CHANNEL_2_ID is None
    assert settings.REQUIRED_CHANNEL_2_URL is None
    assert settings.REQUIRED_CHANNEL_3_ID is None
    assert settings.REQUIRED_CHANNEL_3_URL is None


@pytest.mark.asyncio
async def test_membership_channels_positive_id_rejected(client):
    resp = await client.put(
        "/api/admin/settings/membership-channels",
        json={"channels": [{"id": 1001111111111, "url": "https://t.me/one"}]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_membership_channels_bad_url_rejected(client):
    resp = await client.put(
        "/api/admin/settings/membership-channels",
        json={"channels": [{"id": -1001111111111, "url": "https://example.com/one"}]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_membership_channels_missing_url_rejected(client):
    resp = await client.put(
        "/api/admin/settings/membership-channels",
        json={"channels": [{"id": -1001111111111}]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_membership_channels_too_many_rejected(client):
    resp = await client.put(
        "/api/admin/settings/membership-channels",
        json={
            "channels": [
                {"id": -1000000000000 - i, "url": f"https://t.me/c{i}"}
                for i in range(MAX_REQUIRED_CHANNELS + 1)
            ]
        },
    )
    assert resp.status_code == 422


# ── Override persistence (unit-level, no HTTP) ────────────────────────────


def test_save_settings_override_writes_atomically(tmp_path, monkeypatch):
    override_path = tmp_path / "admin_settings_override.json"
    monkeypatch.setattr("app.core.config.SETTINGS_OVERRIDE_PATH", override_path)

    save_settings_override({"RATE_LIMIT_REQUESTS": 77})

    assert override_path.exists()
    data = json.loads(override_path.read_text(encoding="utf-8"))
    assert data["RATE_LIMIT_REQUESTS"] == 77
    assert settings.RATE_LIMIT_REQUESTS == 77
    # no leftover temp files from the atomic-write step
    assert list(tmp_path.glob(".tmp-*")) == []


def test_load_settings_override_applies_file_on_top_of_defaults(tmp_path, monkeypatch):
    override_path = tmp_path / "admin_settings_override.json"
    override_path.write_text(json.dumps({"RATE_LIMIT_WINDOW_SECONDS": 99}), encoding="utf-8")
    monkeypatch.setattr("app.core.config.SETTINGS_OVERRIDE_PATH", override_path)

    load_settings_override()

    assert settings.RATE_LIMIT_WINDOW_SECONDS == 99


def test_load_settings_override_normalizes_legacy_int_time(tmp_path, monkeypatch):
    """A pre-existing override written as a bare-hour int loads as 'HH:MM'."""
    override_path = tmp_path / "admin_settings_override.json"
    override_path.write_text(
        json.dumps({"DAILY_BROADCAST_HOUR": 14, "SAME_DAY_CUTOFF_HOUR": 9}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.SETTINGS_OVERRIDE_PATH", override_path)

    load_settings_override()

    assert settings.DAILY_BROADCAST_HOUR == "14:00"
    assert settings.SAME_DAY_CUTOFF_HOUR == "09:00"


def test_load_settings_override_bad_time_does_not_drop_other_keys(tmp_path, monkeypatch):
    """One unparseable time value must not discard the rest of the overrides."""
    override_path = tmp_path / "admin_settings_override.json"
    override_path.write_text(
        json.dumps({"DAILY_BROADCAST_HOUR": "not-a-time", "RATE_LIMIT_WINDOW_SECONDS": 88}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.SETTINGS_OVERRIDE_PATH", override_path)

    load_settings_override()

    assert settings.RATE_LIMIT_WINDOW_SECONDS == 88
