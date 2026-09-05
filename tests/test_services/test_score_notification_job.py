"""The out-of-band score notification path, end to end — mocked repos, no DB.

`test_score_notification.py` covers `_format`, which is the message text. This
file covers everything around it: which transaction types are allowed to spawn
a job at all, and what `deliver()` does with the one it is given — the claim,
the send, and the terminal status it stamps in every outcome.

That path had no coverage, and it is the part that can lose or duplicate a
message. It runs in its own session after the score has already committed, so
nothing it does can be rolled back: a double send is a double message to a real
user, and an unstamped row is a message that never arrives.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramForbiddenError

from app.core.config import settings
from app.db.models.reservation import AttendanceStatus
from app.db.models.score import NotifyStatus, ScoreTransactionType
from app.schedulers.jobs.score_notification import (
    _should_notify,
    enqueue_score_notification,
)
from app.services.score_notification import ScoreNotificationService

TX_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
RESERVATION_ID = uuid.uuid4()


@pytest.fixture
def restore_flags():
    """The three notification switches are module-level settings; a test that
    flips one has to put it back or it leaks into the rest of the suite."""
    keys = (
        "SCORE_CHANGE_NOTIFICATIONS_ENABLED",
        "NOTIFY_ON_REWARD",
        "NOTIFY_ON_CANCEL_ROLLBACK",
    )
    original = {k: getattr(settings, k) for k in keys}
    yield
    for key, value in original.items():
        object.__setattr__(settings, key, value)


def _flag(name: str, value: bool) -> None:
    object.__setattr__(settings, name, value)


# ── Which types may spawn a job ───────────────────────────────────────────────

class TestGating:
    def test_the_master_switch_stops_everything(self, restore_flags):
        """It has to stay a real kill switch — an operator who turned score DMs
        off has turned them off, including the attendance ones."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", False)
        _flag("NOTIFY_ON_REWARD", True)

        for ttype in ScoreTransactionType:
            assert _should_notify(ttype.value) is False, ttype

    def test_attendance_needs_no_opt_in_of_its_own(self, restore_flags):
        """Deliberately unlike the two high-churn types below: an attendance
        decision is admin-initiated, happens at most once per reservation, and
        carries an explanation the user has no other way to see. Both per-type
        flags are off here and it still goes out."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        _flag("NOTIFY_ON_REWARD", False)
        _flag("NOTIFY_ON_CANCEL_ROLLBACK", False)

        assert _should_notify(ScoreTransactionType.ATTENDANCE_SCORE.value) is True

    @pytest.mark.parametrize(
        "ttype,flag",
        [
            (ScoreTransactionType.RESERVATION_REWARD.value, "NOTIFY_ON_REWARD"),
            (
                ScoreTransactionType.RESERVATION_CANCELLATION.value,
                "NOTIFY_ON_CANCEL_ROLLBACK",
            ),
        ],
    )
    def test_the_two_retired_types_still_honour_their_flags(
        self, restore_flags, ttype, flag
    ):
        """Nothing writes these any more, but the flags stay wired: a stored
        `true` must not start DMing about historical rows if one is ever
        re-notified."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)

        _flag(flag, False)
        assert _should_notify(ttype) is False
        _flag(flag, True)
        assert _should_notify(ttype) is True

    @pytest.mark.parametrize(
        "ttype",
        [
            ScoreTransactionType.ADMIN_ADJUSTMENT.value,
            ScoreTransactionType.NO_SHOW_PENALTY.value,
        ],
    )
    def test_admin_driven_types_are_on_by_default(self, restore_flags, ttype):
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        assert _should_notify(ttype) is True


class TestEnqueue:
    def test_a_gated_type_never_reaches_the_scheduler(self, restore_flags):
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", False)
        scheduler = MagicMock()

        with patch(
            "app.schedulers.setup.get_scheduler", return_value=scheduler
        ):
            enqueue_score_notification(
                TX_ID, ScoreTransactionType.ATTENDANCE_SCORE.value
            )

        scheduler.add_job.assert_not_called()

    def test_an_allowed_type_is_scheduled_once_per_transaction(self, restore_flags):
        """The job id is keyed on the transaction with replace_existing, so a
        retried caller re-schedules rather than queueing a second DM."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        scheduler = MagicMock()

        with patch("app.schedulers.setup.get_scheduler", return_value=scheduler):
            enqueue_score_notification(
                TX_ID, ScoreTransactionType.ATTENDANCE_SCORE.value
            )

        scheduler.add_job.assert_called_once()
        kwargs = scheduler.add_job.call_args.kwargs
        assert kwargs["id"] == f"score_notify:{TX_ID}"
        assert kwargs["replace_existing"] is True
        assert kwargs["args"] == [str(TX_ID)]

    def test_no_scheduler_does_not_break_the_caller(self, restore_flags):
        """This runs inside the request that recorded the decision. A
        scheduling problem must never cost the user their score."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)

        with patch("app.schedulers.setup.get_scheduler", return_value=None):
            enqueue_score_notification(
                TX_ID, ScoreTransactionType.ATTENDANCE_SCORE.value
            )  # must not raise

    def test_a_failing_scheduler_is_swallowed(self, restore_flags):
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        scheduler = MagicMock()
        scheduler.add_job.side_effect = RuntimeError("scheduler is down")

        with patch("app.schedulers.setup.get_scheduler", return_value=scheduler):
            enqueue_score_notification(
                TX_ID, ScoreTransactionType.ATTENDANCE_SCORE.value
            )  # must not raise


# ── deliver(): the delivery itself ────────────────────────────────────────────

def _tx(
    *,
    ttype=ScoreTransactionType.ATTENDANCE_SCORE.value,
    delta=10,
    reason="Hosted the session",
    notify_status=NotifyStatus.PENDING.value,
    reservation_id=RESERVATION_ID,
    meta=None,
    blocked=False,
):
    return SimpleNamespace(
        id=TX_ID,
        transaction_type=ttype,
        score_delta=delta,
        reason=reason,
        notify_status=notify_status,
        reservation_id=reservation_id,
        meta=meta,
        user=SimpleNamespace(
            id=USER_ID,
            telegram_id=555,
            participation_score=42,
            bot_blocked=blocked,
        ),
    )


def _reservation(attendance_status=AttendanceStatus.ATTENDED.value):
    return SimpleNamespace(
        attendance_status=attendance_status,
        slot=None,
        channel=None,
    )


def _service(*, tx, claimed=True, reservation=None, send=(True, None)):
    svc = ScoreNotificationService.__new__(ScoreNotificationService)
    svc._session = AsyncMock()
    svc._tx_repo = AsyncMock()
    svc._tx_repo.get_with_user = AsyncMock(return_value=tx)
    svc._tx_repo.claim_for_notification = AsyncMock(return_value=claimed)
    svc._tx_repo.mark_notified = AsyncMock()
    svc._res_repo = AsyncMock()
    svc._res_repo.get_reservation_with_details = AsyncMock(return_value=reservation)
    svc._user_repo = AsyncMock()
    svc._notif = AsyncMock()
    if isinstance(send, Exception):
        svc._notif.send = AsyncMock(side_effect=send)
    else:
        svc._notif.send = AsyncMock(return_value=send)
    return svc


def _sent_text(svc) -> str:
    return svc._notif.send.await_args.args[1]


class TestDeliverySucceeds:
    @pytest.mark.asyncio
    async def test_it_claims_before_sending(self, restore_flags):
        """Order is the whole idempotency story: win the claim, then do I/O. A
        send-then-claim would double-message whenever the job ran twice."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=_tx(), reservation=_reservation())

        await svc.deliver(TX_ID)

        svc._tx_repo.claim_for_notification.assert_awaited_once_with(TX_ID)
        svc._notif.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_successful_send_is_stamped_sent(self, restore_flags):
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=_tx(), reservation=_reservation())

        await svc.deliver(TX_ID)

        svc._tx_repo.mark_notified.assert_awaited_once_with(TX_ID, NotifyStatus.SENT)

    @pytest.mark.asyncio
    async def test_the_attendance_outcome_reaches_the_message(self, restore_flags):
        """The end-to-end version of what the `_format` tests assert in
        isolation: the column has to be read and passed through."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(
            tx=_tx(delta=2),
            reservation=_reservation(AttendanceStatus.ABSENT.value),
        )

        await svc.deliver(TX_ID)

        text = _sent_text(svc)
        assert "not having attended" in text
        assert "You received <b>+2</b> point(s)" in text

    @pytest.mark.asyncio
    async def test_the_outcome_falls_back_to_the_ledger_meta(self, restore_flags):
        """score_transactions.reservation_id is ON DELETE SET NULL, so the
        reservation can be gone by the time the job runs. The mirror in `meta`
        is what is left, and without it the DM would state a score with no
        outcome."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(
            tx=_tx(
                reservation_id=None,
                meta={"attendance_status": AttendanceStatus.ABSENT.value},
            ),
            reservation=None,
        )

        await svc.deliver(TX_ID)

        assert "not having attended" in _sent_text(svc)
        svc._res_repo.get_reservation_with_details.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_non_attendance_type_never_reads_an_outcome(self, restore_flags):
        """A no-show penalty's `meta` could hold anything; only an attendance
        row is allowed to produce the outcome line."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(
            tx=_tx(
                ttype=ScoreTransactionType.NO_SHOW_PENALTY.value,
                delta=-1,
                meta={"attendance_status": AttendanceStatus.ABSENT.value},
            ),
            reservation=_reservation(AttendanceStatus.ABSENT.value),
        )

        await svc.deliver(TX_ID)

        text = _sent_text(svc)
        assert "not having attended" not in text
        assert "<b>Score Update</b>" in text

    @pytest.mark.asyncio
    async def test_a_zero_score_decision_is_still_delivered(self, restore_flags):
        """"Attended, worth nothing" is a decision the user is owed a message
        about — there is nothing in the delta to tell them what happened."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=_tx(delta=0), reservation=_reservation())

        await svc.deliver(TX_ID)

        svc._notif.send.assert_awaited_once()
        assert "unchanged" in _sent_text(svc)
        svc._tx_repo.mark_notified.assert_awaited_once_with(TX_ID, NotifyStatus.SENT)


class TestDeliveryIsRefused:
    @pytest.mark.asyncio
    async def test_the_master_switch_stops_delivery_too(self, restore_flags):
        """Checked here as well as at enqueue time: a job scheduled before the
        switch was flipped must not still send."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", False)
        svc = _service(tx=_tx(), reservation=_reservation())

        await svc.deliver(TX_ID)

        svc._tx_repo.get_with_user.assert_not_awaited()
        svc._notif.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_transaction_sends_nothing(self, restore_flags):
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=None)

        await svc.deliver(TX_ID)

        svc._notif.send.assert_not_awaited()
        svc._tx_repo.mark_notified.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_already_stamped_row_is_not_resent(self, restore_flags):
        """The APScheduler job has a misfire grace of an hour and can run twice.
        This is the check that makes a second run a no-op."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=_tx(notify_status=NotifyStatus.SENT.value))

        await svc.deliver(TX_ID)

        svc._tx_repo.claim_for_notification.assert_not_awaited()
        svc._notif.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_lost_claim_sends_nothing(self, restore_flags):
        """Two runs can both see `pending`; only the one that wins the DB claim
        may send."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=_tx(), claimed=False, reservation=_reservation())

        await svc.deliver(TX_ID)

        svc._notif.send.assert_not_awaited()
        svc._tx_repo.mark_notified.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_blocked_user_is_skipped_not_failed(self, restore_flags):
        """SKIPPED, not FAILED: nothing went wrong, there is just nobody to
        tell. It also must not burn the claim."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(tx=_tx(blocked=True))

        await svc.deliver(TX_ID)

        svc._tx_repo.mark_notified.assert_awaited_once_with(
            TX_ID, NotifyStatus.SKIPPED
        )
        svc._notif.send.assert_not_awaited()


class TestDeliveryFails:
    @pytest.mark.asyncio
    async def test_a_refused_send_is_stamped_failed(self, restore_flags):
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(
            tx=_tx(), reservation=_reservation(), send=(False, "flood wait")
        )

        await svc.deliver(TX_ID)

        svc._tx_repo.mark_notified.assert_awaited_once_with(TX_ID, NotifyStatus.FAILED)

    @pytest.mark.asyncio
    async def test_a_user_who_blocked_the_bot_is_recorded_as_such(self, restore_flags):
        """The score has already committed, so this cannot raise. It marks the
        user blocked so the next notification is skipped before any I/O."""
        _flag("SCORE_CHANGE_NOTIFICATIONS_ENABLED", True)
        svc = _service(
            tx=_tx(),
            reservation=_reservation(),
            send=TelegramForbiddenError(method=MagicMock(), message="blocked"),
        )

        await svc.deliver(TX_ID)  # must not raise

        svc._user_repo.mark_bot_blocked.assert_awaited_once_with(USER_ID)
        svc._tx_repo.mark_notified.assert_awaited_once_with(TX_ID, NotifyStatus.FAILED)
