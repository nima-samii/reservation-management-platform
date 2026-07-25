"""DB-backed tests for Sprint-3 marketing foundation: template CRUD, draft
lifecycle, and recurring-rule due logic.

Requires the test Postgres database configured in tests/conftest.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.user_broadcast import UserBroadcastStatus
from app.repositories.user_broadcast import (
    BroadcastRecurringRuleRepository,
    BroadcastTemplateRepository,
    UserBroadcastRecipientRepository,
    UserBroadcastRepository,
)


# ── Template CRUD ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_template_crud(db_session):
    repo = BroadcastTemplateRepository(db_session)

    t = await repo.create(name="Welcome", message="Hello!", parse_mode="HTML")
    await db_session.flush()
    assert t.id is not None

    rows = await repo.list_all()
    assert len(rows) == 1

    updated = await repo.update(t.id, name="Welcome v2", message="Hi there")
    assert updated.name == "Welcome v2"
    assert updated.message == "Hi there"

    await repo.delete(updated)
    await db_session.flush()
    assert await repo.list_all() == []


@pytest.mark.asyncio
async def test_template_with_media(db_session):
    repo = BroadcastTemplateRepository(db_session)
    t = await repo.create(
        name="Promo", message="See attached", parse_mode="HTML",
        media_type="photo", media_file_id="FILEID123",
    )
    await db_session.flush()
    assert t.media_type == "photo"
    assert t.media_file_id == "FILEID123"


# ── Draft lifecycle ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_lifecycle(db_session):
    repo = UserBroadcastRepository(db_session)
    recip_repo = UserBroadcastRecipientRepository(db_session)

    draft = await repo.create(
        message="draft msg",
        parse_mode="HTML",
        audience_type="all_users",
        created_by="admin",
        status=UserBroadcastStatus.DRAFT.value,
        filters={},
    )
    await db_session.flush()
    assert draft.status == "draft"
    # A draft never has recipient rows.
    assert await recip_repo.get_pending(draft.id) == []

    # Editable.
    await repo.update_draft(draft.id, message="edited", media_type="document", media_file_id="D1")
    await db_session.flush()
    reloaded = await repo.get_by_id(draft.id)
    assert reloaded.message == "edited"
    assert reloaded.media_type == "document"
    assert reloaded.media_file_id == "D1"

    # Launchable.
    await repo.set_status(draft.id, UserBroadcastStatus.PENDING.value)
    await db_session.flush()
    assert (await repo.get_by_id(draft.id)).status == "pending"


# ── Recurring rule due-logic ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recurring_rule_due_and_deactivate(db_session):
    bcast_repo = UserBroadcastRepository(db_session)
    rule_repo = BroadcastRecurringRuleRepository(db_session)

    source = await bcast_repo.create(
        message="recurring source",
        parse_mode="HTML",
        audience_type="all_users",
        created_by="admin",
        status=UserBroadcastStatus.DRAFT.value,
        filters={},
    )
    await db_session.flush()

    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    rule = await rule_repo.create(
        broadcast_id=source.id,
        frequency="daily",
        interval=1,
        next_run_at=now - timedelta(minutes=1),  # already due
    )
    await db_session.flush()

    due = await rule_repo.get_due(now)
    assert any(r.id == rule.id for r in due)

    # Advance and it is no longer due.
    await rule_repo.set_next_run(rule.id, now + timedelta(days=1))
    await db_session.flush()
    assert all(r.id != rule.id for r in await rule_repo.get_due(now))

    # Deactivating excludes it even when due.
    await rule_repo.set_next_run(rule.id, now - timedelta(minutes=1))
    await rule_repo.set_active(rule.id, False)
    await db_session.flush()
    assert all(r.id != rule.id for r in await rule_repo.get_due(now))


@pytest.mark.asyncio
async def test_scheduled_due_lookup(db_session):
    repo = UserBroadcastRepository(db_session)
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)

    await repo.create(
        message="past", parse_mode="HTML", audience_type="all_users", created_by="a",
        status=UserBroadcastStatus.SCHEDULED.value, scheduled_for=now - timedelta(hours=1), filters={},
    )
    await repo.create(
        message="future", parse_mode="HTML", audience_type="all_users", created_by="a",
        status=UserBroadcastStatus.SCHEDULED.value, scheduled_for=now + timedelta(hours=1), filters={},
    )
    await db_session.flush()

    due = await repo.get_due_scheduled(now)
    assert len(due) == 1
    assert due[0].message == "past"
