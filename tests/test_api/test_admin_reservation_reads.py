"""API tests for the reservation read paths — mocked repository, no DB.

Phases 1–6 made an attendance decision recordable but left every read path
blind to it: the list, the detail and the export returned only the retired
`no_show_applied` flag, so a decision an admin had just made was invisible
everywhere except the response that created it. These tests pin the HTTP shape
of the fix, plus the `attendance` filter that makes the pending queue reachable.

The repository is patched out — what the filter does in SQL is the repository's
business, so here we only assert the parameter reaches it and that an unknown
value is refused rather than ignored.
"""
import csv
import io
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
from app.db.session import get_db_session

MARKED_AT = datetime(2026, 6, 21, 9, 30, tzinfo=timezone.utc)

_EMPTY_SUMMARY = {
    "total": 0,
    "active": 0,
    "completed": 0,
    "cancelled": 0,
    "no_show": 0,
    "attended": 0,
    "awaiting_decision": 0,
}


def _make_res(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        status="completed",
        notes=None,
        attendance_status=None,
        attendance_score_delta=None,
        attendance_reason=None,
        attendance_marked_by=None,
        attendance_marked_at=None,
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
            participation_score=7,
        ),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _decided(status="attended", delta=10):
    return _make_res(
        attendance_status=status,
        attendance_score_delta=delta,
        attendance_reason="Joined and contributed",
        attendance_marked_by="alice",
        attendance_marked_at=MARKED_AT,
    )


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


def _patch_repo(monkeypatch, *, rows=(), total=None, summary=None):
    repo = MagicMock()
    repo.admin_list = AsyncMock(
        return_value=(list(rows), total if total is not None else len(rows))
    )
    repo.admin_summary = AsyncMock(return_value=summary or dict(_EMPTY_SUMMARY))
    repo.admin_export = AsyncMock(return_value=list(rows))
    repo.get_reservation_admin_detail = AsyncMock(
        return_value=rows[0] if rows else None
    )
    monkeypatch.setattr(res_mod, "ReservationRepository", MagicMock(return_value=repo))
    return repo


# ── The decision is visible in the list and the detail ────────────────────────

class TestDecisionIsExposed:
    @pytest.mark.asyncio
    async def test_the_list_carries_all_five_columns(self, client, monkeypatch):
        res = _decided(status="absent", delta=-5)
        _patch_repo(monkeypatch, rows=[res])

        body = (await client.get("/api/admin/reservations")).json()

        item = body["items"][0]
        assert item["attendance_status"] == "absent"
        assert item["attendance_score_delta"] == -5
        assert item["attendance_reason"] == "Joined and contributed"
        assert item["attendance_marked_by"] == "alice"
        assert item["attendance_marked_at"].startswith("2026-06-21T09:30")

    @pytest.mark.asyncio
    async def test_an_undecided_reservation_reports_nulls_not_absence(
        self, client, monkeypatch
    ):
        """Five nulls, so the panel can tell "not judged yet" from "attended,
        worth nothing" — which a default of 0 would have collapsed."""
        _patch_repo(monkeypatch, rows=[_make_res()])

        item = (await client.get("/api/admin/reservations")).json()["items"][0]

        assert item["attendance_status"] is None
        assert item["attendance_score_delta"] is None
        assert item["no_show_applied"] is False

    @pytest.mark.asyncio
    async def test_a_zero_score_decision_is_not_confused_with_no_decision(
        self, client, monkeypatch
    ):
        _patch_repo(monkeypatch, rows=[_decided(delta=0)])

        item = (await client.get("/api/admin/reservations")).json()["items"][0]

        assert item["attendance_status"] == "attended"
        assert item["attendance_score_delta"] == 0

    @pytest.mark.asyncio
    async def test_the_detail_endpoint_carries_the_decision(self, client, monkeypatch):
        res = _decided()
        _patch_repo(monkeypatch, rows=[res])

        body = (await client.get(f"/api/admin/reservations/{res.id}")).json()

        assert body["attendance_status"] == "attended"
        assert body["attendance_score_delta"] == 10

    @pytest.mark.asyncio
    async def test_the_legacy_flag_stays_separate_from_the_decision(
        self, client, monkeypatch
    ):
        """The retired penalty always meant -1 and cannot be re-decided, so it
        must not masquerade as an admin's choice."""
        res = _make_res(notes='{"no_show_penalty_applied": true}')
        _patch_repo(monkeypatch, rows=[res])

        item = (await client.get("/api/admin/reservations")).json()["items"][0]

        assert item["no_show_applied"] is True
        assert item["attendance_status"] is None


# ── The summary counts ────────────────────────────────────────────────────────

class TestSummary:
    @pytest.mark.asyncio
    async def test_the_new_counts_are_passed_through(self, client, monkeypatch):
        _patch_repo(
            monkeypatch,
            rows=[],
            summary={
                "total": 9,
                "active": 2,
                "completed": 6,
                "cancelled": 1,
                "no_show": 3,
                "attended": 2,
                "awaiting_decision": 1,
            },
        )

        summary = (await client.get("/api/admin/reservations")).json()["summary"]

        assert summary["no_show"] == 3
        assert summary["attended"] == 2
        assert summary["awaiting_decision"] == 1

    @pytest.mark.asyncio
    async def test_a_summary_without_the_new_keys_still_serializes(
        self, client, monkeypatch
    ):
        """The two new counts default to 0 rather than being required, so a
        cached or older summary payload cannot 500 the whole list."""
        _patch_repo(
            monkeypatch,
            rows=[],
            summary={
                "total": 1,
                "active": 1,
                "completed": 0,
                "cancelled": 0,
                "no_show": 0,
            },
        )

        summary = (await client.get("/api/admin/reservations")).json()["summary"]

        assert summary["attended"] == 0
        assert summary["awaiting_decision"] == 0


# ── The attendance filter ─────────────────────────────────────────────────────

class TestAttendanceFilter:
    @pytest.mark.parametrize(
        "value", ["pending", "decided", "attended", "absent"]
    )
    @pytest.mark.asyncio
    async def test_each_valid_value_reaches_the_repository(
        self, client, monkeypatch, value
    ):
        repo = _patch_repo(monkeypatch, rows=[])

        resp = await client.get(f"/api/admin/reservations?attendance={value}")

        assert resp.status_code == 200
        assert repo.admin_list.await_args.kwargs["attendance"] == value

    @pytest.mark.asyncio
    async def test_the_summary_ignores_the_filter(self, client, monkeypatch):
        """The counts are the totals the filter is pressed against. Narrowing
        them by the current selection would make every card agree with itself."""
        repo = _patch_repo(monkeypatch, rows=[])

        await client.get("/api/admin/reservations?attendance=pending")

        assert "attendance" not in repo.admin_summary.await_args.kwargs

    @pytest.mark.asyncio
    async def test_an_unknown_value_is_refused_not_ignored(self, client, monkeypatch):
        """Dropping it would return an unfiltered page that looks filtered —
        the worst outcome for a queue an admin works through row by row."""
        _patch_repo(monkeypatch, rows=[])

        resp = await client.get("/api/admin/reservations?attendance=maybe")

        assert resp.status_code == 422
        assert "pending" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_no_filter_means_no_narrowing(self, client, monkeypatch):
        repo = _patch_repo(monkeypatch, rows=[])

        await client.get("/api/admin/reservations")

        assert repo.admin_list.await_args.kwargs["attendance"] is None

    @pytest.mark.asyncio
    async def test_the_export_accepts_it_too(self, client, monkeypatch):
        repo = _patch_repo(monkeypatch, rows=[])

        resp = await client.get(
            "/api/admin/reservations/export"
            "?date_from=2026-06-01&date_to=2026-06-30&attendance=absent"
        )

        assert resp.status_code == 200
        assert repo.admin_export.await_args.kwargs["attendance"] == "absent"

    @pytest.mark.asyncio
    async def test_the_export_refuses_an_unknown_value(self, client, monkeypatch):
        _patch_repo(monkeypatch, rows=[])

        resp = await client.get(
            "/api/admin/reservations/export"
            "?date_from=2026-06-01&date_to=2026-06-30&attendance=nope"
        )

        assert resp.status_code == 422


# ── The CSV export ────────────────────────────────────────────────────────────

class TestExportColumns:
    async def _rows(self, client):
        resp = await client.get(
            "/api/admin/reservations/export?date_from=2026-06-01&date_to=2026-06-30"
        )
        assert resp.status_code == 200
        return list(csv.reader(io.StringIO(resp.text)))

    @pytest.mark.asyncio
    async def test_the_new_columns_are_appended_after_the_old_ones(
        self, client, monkeypatch
    ):
        """Appended, not inserted: consumers read this file by column position
        as often as by header."""
        _patch_repo(monkeypatch, rows=[_decided()])

        header = (await self._rows(client))[0]

        assert header[:11] == [
            "reservation_id",
            "slot_datetime",
            "slot_time_local",
            "channel_name",
            "user_public_code",
            "user_full_name",
            "country",
            "gender",
            "score_at_export",
            "status",
            "no_show_applied",
        ]
        assert header[11:] == [
            "attendance_status",
            "attendance_score",
            "attendance_reason",
            "attendance_marked_by",
            "attendance_marked_at",
        ]

    @pytest.mark.asyncio
    async def test_a_decision_is_written_out(self, client, monkeypatch):
        _patch_repo(monkeypatch, rows=[_decided(status="absent", delta=-5)])

        row = (await self._rows(client))[1]

        assert row[11] == "absent"
        assert row[12] == "-5"
        assert row[13] == "Joined and contributed"
        assert row[14] == "alice"
        assert row[15].startswith("2026-06-21T")

    @pytest.mark.asyncio
    async def test_a_zero_score_is_a_zero_not_a_blank(self, client, monkeypatch):
        """`or ""` here would have blanked the one value this feature exists to
        make expressible."""
        _patch_repo(monkeypatch, rows=[_decided(delta=0)])

        row = (await self._rows(client))[1]

        assert row[12] == "0"

    @pytest.mark.asyncio
    async def test_an_undecided_reservation_leaves_the_cells_empty(
        self, client, monkeypatch
    ):
        _patch_repo(monkeypatch, rows=[_make_res()])

        row = (await self._rows(client))[1]

        assert row[11:] == ["", "", "", "", ""]

    @pytest.mark.asyncio
    async def test_the_json_export_carries_the_decision(self, client, monkeypatch):
        _patch_repo(monkeypatch, rows=[_decided(delta=0)])

        resp = await client.get(
            "/api/admin/reservations/export"
            "?date_from=2026-06-01&date_to=2026-06-30&format=json"
        )

        assert resp.status_code == 200
        assert resp.json()[0]["attendance_score_delta"] == 0
