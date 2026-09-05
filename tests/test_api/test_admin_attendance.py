"""API tests for POST /api/admin/reservations/{id}/attendance — mocked, no DB.

The service layer is patched out, so these cover only the HTTP contract:
request validation, status-code mapping for each way a decision can be refused,
the response shape, and that the admin audit log is written on success (and only
on success).

The request-schema tests matter more than usual here. The service enforces the
same bounds, but the schema is what turns a bad body into a 422 instead of a
500, and it is the only layer the admin panel's form can see.
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
    AttendanceAlreadyRecordedError,
    AttendanceNotDecidableError,
    LegacyNoShowRecordedError,
    NotFoundError,
    ValidationError,
)
from app.db.models.reservation import AttendanceStatus, ReservationStatus
from app.db.session import get_db_session
from app.services.reservation import ATTENDANCE_REASON_MAX, ATTENDANCE_SCORE_LIMIT

RESERVATION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
TX_ID = uuid.uuid4()
MARKED_AT = datetime(2026, 6, 21, 9, 30, tzinfo=timezone.utc)


def _outcome(attendance_status=AttendanceStatus.ATTENDED.value, delta=10, score=42):
    return SimpleNamespace(
        reservation=SimpleNamespace(
            id=RESERVATION_ID,
            user_id=USER_ID,
            attendance_marked_by="admin",
            attendance_marked_at=MARKED_AT,
        ),
        transaction_id=TX_ID,
        attendance_status=attendance_status,
        score_delta=delta,
        reason="Hosted the session",
        new_score=score,
    )


def _body(**overrides):
    body = {
        "attendance_status": "attended",
        "score_delta": 10,
        "reason": "Hosted the session",
    }
    body.update(overrides)
    return body


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
    svc.record_attendance = AsyncMock(return_value=return_value, side_effect=side_effect)
    monkeypatch.setattr(res_mod, "ReservationService", MagicMock(return_value=svc))
    return svc


def _url(reservation_id=RESERVATION_ID) -> str:
    return f"/api/admin/reservations/{reservation_id}/attendance"


# ── Success ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_records_the_decision_and_echoes_it_back(client, monkeypatch):
    svc = _patch_service(monkeypatch, return_value=_outcome())

    resp = await client.post(_url(), json=_body())

    assert resp.status_code == 200
    assert resp.json() == {
        "reservation_id": str(RESERVATION_ID),
        "user_id": str(USER_ID),
        "attendance_status": "attended",
        "score_delta": 10,
        "reason": "Hosted the session",
        "new_score": 42,
        "transaction_id": str(TX_ID),
        # Echoed so the panel can render the recorded row without re-fetching
        # and without inventing a client-side timestamp.
        "marked_by": "admin",
        "marked_at": "2026-06-21T09:30:00Z",
    }
    kwargs = svc.record_attendance.await_args.kwargs
    assert kwargs["attendance_status"] is AttendanceStatus.ATTENDED
    assert kwargs["score_delta"] == 10
    assert kwargs["actor"] == "admin"


@pytest.mark.asyncio
async def test_success_is_audited_with_the_decision(client, monkeypatch):
    _patch_service(monkeypatch, return_value=_outcome(delta=-5))

    resp = await client.post(_url(), json=_body(score_delta=-5))

    assert resp.status_code == 200
    client._audit_log.assert_awaited_once()
    kwargs = client._audit_log.await_args.kwargs
    assert kwargs["action"] == "attendance_recorded"
    assert kwargs["entity_type"] == "reservation"
    assert kwargs["entity_id"] == str(RESERVATION_ID)
    assert kwargs["admin_username"] == "admin"
    # The audit line has to carry the score, signed — it is the only record of
    # what the admin chose, and the decision is immutable.
    assert "score_delta=-5" in kwargs["details"]
    assert f"tx_id={TX_ID}" in kwargs["details"]


@pytest.mark.parametrize(
    "attendance_status,delta",
    [
        ("attended", 10),
        ("attended", 0),
        ("attended", -5),
        ("absent", 2),
        ("absent", 0),
        ("absent", -20),
    ],
)
@pytest.mark.asyncio
async def test_every_outcome_and_score_combination_is_accepted(
    client, monkeypatch, attendance_status, delta
):
    """The HTTP layer must not reintroduce the coupling the feature removes."""
    svc = _patch_service(
        monkeypatch, return_value=_outcome(attendance_status, delta)
    )

    resp = await client.post(
        _url(), json=_body(attendance_status=attendance_status, score_delta=delta)
    )

    assert resp.status_code == 200
    assert resp.json()["score_delta"] == delta
    assert svc.record_attendance.await_args.kwargs["score_delta"] == delta


# ── Refusals ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_reservation_returns_404(client, monkeypatch):
    _patch_service(monkeypatch, side_effect=NotFoundError("Reservation"))

    resp = await client.post(_url(uuid.uuid4()), json=_body())

    assert resp.status_code == 404
    client._audit_log.assert_not_awaited()


@pytest.mark.parametrize(
    "exc",
    [
        AttendanceAlreadyRecordedError(),
        AttendanceNotDecidableError("active"),
        LegacyNoShowRecordedError(),
    ],
    ids=["already-decided", "not-completed", "legacy-no-show"],
)
@pytest.mark.asyncio
async def test_the_three_conflicts_return_409_with_their_own_message(
    client, monkeypatch, exc
):
    """All three are state conflicts, but the admin's next move differs for
    each — wait for the lifecycle job, look at the existing decision, or accept
    the old penalty — so the message must survive the mapping."""
    _patch_service(monkeypatch, side_effect=exc)

    resp = await client.post(_url(), json=_body())

    assert resp.status_code == 409
    assert resp.json()["detail"] == exc.message
    client._audit_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_not_completed_conflict_names_the_current_status(client, monkeypatch):
    # A just-passed session stays ACTIVE until the :00/:30 lifecycle job, and
    # the status is what tells the admin to wait rather than retry.
    _patch_service(monkeypatch, side_effect=AttendanceNotDecidableError("active"))

    resp = await client.post(_url(), json=_body())

    assert "active" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_service_validation_error_returns_422(client, monkeypatch):
    _patch_service(monkeypatch, side_effect=ValidationError("Nope"))

    resp = await client.post(_url(), json=_body())

    assert resp.status_code == 422
    client._audit_log.assert_not_awaited()


# ── Request validation ────────────────────────────────────────────────────────

class TestRequestValidation:
    @pytest.mark.asyncio
    async def test_an_unknown_outcome_is_rejected(self, client, monkeypatch):
        svc = _patch_service(monkeypatch, return_value=_outcome())

        resp = await client.post(
            _url(), json=_body(attendance_status="no_show")
        )

        assert resp.status_code == 422
        svc.record_attendance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_outcome_is_required(self, client, monkeypatch):
        _patch_service(monkeypatch, return_value=_outcome())
        body = _body()
        del body["attendance_status"]

        assert (await client.post(_url(), json=body)).status_code == 422

    @pytest.mark.asyncio
    async def test_the_score_is_required(self, client, monkeypatch):
        """There is no default. A missing score is an unfinished form, not a
        zero — and zero is itself a real decision."""
        _patch_service(monkeypatch, return_value=_outcome())
        body = _body()
        del body["score_delta"]

        assert (await client.post(_url(), json=body)).status_code == 422

    @pytest.mark.parametrize(
        "delta", [ATTENDANCE_SCORE_LIMIT + 1, -ATTENDANCE_SCORE_LIMIT - 1]
    )
    @pytest.mark.asyncio
    async def test_a_score_beyond_the_bound_is_rejected(
        self, client, monkeypatch, delta
    ):
        svc = _patch_service(monkeypatch, return_value=_outcome())

        resp = await client.post(_url(), json=_body(score_delta=delta))

        assert resp.status_code == 422
        svc.record_attendance.assert_not_awaited()

    @pytest.mark.parametrize(
        "delta", [ATTENDANCE_SCORE_LIMIT, -ATTENDANCE_SCORE_LIMIT]
    )
    @pytest.mark.asyncio
    async def test_the_bound_itself_is_accepted(self, client, monkeypatch, delta):
        _patch_service(monkeypatch, return_value=_outcome(delta=delta))

        resp = await client.post(_url(), json=_body(score_delta=delta))

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_a_fractional_score_is_rejected(self, client, monkeypatch):
        _patch_service(monkeypatch, return_value=_outcome())

        assert (
            await client.post(_url(), json=_body(score_delta=1.5))
        ).status_code == 422

    @pytest.mark.asyncio
    async def test_the_reason_is_required(self, client, monkeypatch):
        """It is quoted back to the user, so a decision with no explanation is
        not a decision they can act on."""
        _patch_service(monkeypatch, return_value=_outcome())
        body = _body()
        del body["reason"]

        assert (await client.post(_url(), json=body)).status_code == 422

    @pytest.mark.parametrize("reason", ["", "   ", "\n\t "])
    @pytest.mark.asyncio
    async def test_a_blank_reason_is_rejected(self, client, monkeypatch, reason):
        # min_length alone lets whitespace through; the validator is what stops
        # a message that quotes back nothing.
        svc = _patch_service(monkeypatch, return_value=_outcome())

        resp = await client.post(_url(), json=_body(reason=reason))

        assert resp.status_code == 422
        svc.record_attendance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_overlong_reason_is_rejected(self, client, monkeypatch):
        _patch_service(monkeypatch, return_value=_outcome())

        resp = await client.post(
            _url(), json=_body(reason="x" * (ATTENDANCE_REASON_MAX + 1))
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_the_reason_reaches_the_service_stripped(self, client, monkeypatch):
        svc = _patch_service(monkeypatch, return_value=_outcome())

        await client.post(_url(), json=_body(reason="  Joined late  "))

        assert svc.record_attendance.await_args.kwargs["reason"] == "Joined late"


# ── The deprecated no-show endpoint, during the changeover ────────────────────

@pytest.mark.asyncio
async def test_the_legacy_no_show_endpoint_refuses_a_decided_reservation(
    client, monkeypatch
):
    """Both endpoints score the same session. The shipped panel still calls the
    old one, so until its UI is replaced the guard has to run in both
    directions or one reservation can be charged twice."""
    res = SimpleNamespace(
        id=RESERVATION_ID,
        user_id=USER_ID,
        status=ReservationStatus.COMPLETED,
        notes=None,
        attendance_status=AttendanceStatus.ATTENDED.value,
        user=SimpleNamespace(participation_score=42),
    )
    monkeypatch.setattr(
        res_mod,
        "ReservationRepository",
        MagicMock(
            return_value=MagicMock(
                get_reservation_admin_detail=AsyncMock(return_value=res),
                save=AsyncMock(),
            )
        ),
    )
    score_svc = MagicMock(apply_no_show_penalty=AsyncMock())
    monkeypatch.setattr(
        res_mod, "ParticipationScoreService", MagicMock(return_value=score_svc)
    )

    resp = await client.post(f"/api/admin/reservations/{RESERVATION_ID}/no-show")

    assert resp.status_code == 409
    assert "attendance decision" in resp.json()["detail"]
    score_svc.apply_no_show_penalty.assert_not_awaited()
    client._audit_log.assert_not_awaited()


def test_the_legacy_no_show_endpoint_is_marked_deprecated():
    """Asserted through the OpenAPI schema rather than the route object: the
    schema is what the panel and any client are generated from, and it is the
    only place the deprecation is actually visible."""
    paths = create_app().openapi()["paths"]

    old = paths["/api/admin/reservations/{reservation_id}/no-show"]["post"]
    new = paths["/api/admin/reservations/{reservation_id}/attendance"]["post"]
    assert old["deprecated"] is True
    assert new.get("deprecated") is not True
