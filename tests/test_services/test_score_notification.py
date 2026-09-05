"""Tests for ScoreNotificationService._format — pure, no DB.

Covers the message body:
  * sign-aware headline (gain vs loss vs unchanged)
  * reason line + current score always present
  * linked-reservation details (date/time/channel) appended when provided,
    e.g. for a no-show penalty
  * attendance decisions: the outcome line and its own title
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.db.models.reservation import AttendanceStatus
from app.db.models.score import ScoreTransactionType
from app.services.score_notification import ScoreNotificationService


def _reservation():
    return SimpleNamespace(
        slot=SimpleNamespace(
            slot_datetime=datetime(2026, 6, 20, 15, 0, tzinfo=timezone.utc),
        ),
        channel=SimpleNamespace(name="Channel 1"),
    )


def test_format_loss_without_reservation():
    text = ScoreNotificationService._format(
        ScoreTransactionType.ADMIN_ADJUSTMENT.value, -1, "Manual fix", 9
    )
    assert "You lost <b>1</b> point(s)." in text
    assert "Reason: Manual fix" in text
    assert "Your current score: <b>9</b>" in text
    # No reservation → no slot details.
    assert "📅 Date:" not in text


def test_format_no_show_includes_reservation_details():
    text = ScoreNotificationService._format(
        ScoreTransactionType.NO_SHOW_PENALTY.value,
        -1,
        "No-show penalty applied by admin",
        9,
        _reservation(),
    )
    assert "You lost <b>1</b> point(s)." in text
    assert "No-show penalty applied by admin" in text
    assert "20 June 2026" in text
    assert "Channel 1" in text
    assert "Your current score: <b>9</b>" in text


# ── Zero delta ────────────────────────────────────────────────────────────────

def test_zero_delta_does_not_read_as_a_loss():
    """A zero-score decision is a real outcome, not a loss of nothing."""
    text = ScoreNotificationService._format(
        ScoreTransactionType.ATTENDANCE_SCORE.value,
        0,
        "Attended, no points this week",
        12,
        _reservation(),
        AttendanceStatus.ATTENDED.value,
    )
    assert "You lost" not in text
    assert "You received" not in text
    assert "Your score is unchanged (<b>0</b> points)." in text
    assert "Your current score: <b>12</b>" in text


def test_zero_delta_wording_is_not_attendance_specific():
    # The bug was in the sign branches, so it applied to every type that can
    # carry a zero — an admin adjustment of 0 included.
    text = ScoreNotificationService._format(
        ScoreTransactionType.ADMIN_ADJUSTMENT.value, 0, "Reviewed, no change", 5
    )
    assert "You lost" not in text
    assert "unchanged" in text


# ── Attendance decisions ──────────────────────────────────────────────────────

class TestAttendanceMessage:
    @pytest.mark.parametrize(
        "attendance_status,expected",
        [
            (AttendanceStatus.ATTENDED.value, "✅ You attended this session."),
            (
                AttendanceStatus.ABSENT.value,
                "❌ You were marked as not having attended this session.",
            ),
        ],
    )
    def test_the_outcome_is_stated_on_its_own_line(self, attendance_status, expected):
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            5,
            "Joined and participated",
            20,
            _reservation(),
            attendance_status,
        )
        assert expected in text

    def test_attendance_gets_its_own_title(self):
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            5,
            "Joined and participated",
            20,
            _reservation(),
            AttendanceStatus.ATTENDED.value,
        )
        assert "<b>Session Attendance</b>" in text
        assert "Score Update" not in text

    def test_the_outcome_precedes_the_score(self):
        """The outcome is what the score is about, and the number cannot express
        it — an absence may still carry points."""
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            2,
            "Told us in advance",
            8,
            _reservation(),
            AttendanceStatus.ABSENT.value,
        )
        assert text.index("not having attended") < text.index("You received")

    def test_absent_can_still_award_points(self):
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            2,
            "Told us in advance",
            8,
            _reservation(),
            AttendanceStatus.ABSENT.value,
        )
        assert "🎉 You received <b>+2</b> point(s)!" in text

    def test_the_admins_explanation_is_quoted_back(self):
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            -5,
            "Left after five minutes",
            3,
            _reservation(),
            AttendanceStatus.ATTENDED.value,
        )
        assert "Reason: Left after five minutes" in text
        # Attended, negative score — a combination the feature must allow.
        assert "You lost <b>5</b> point(s)." in text

    def test_the_explanation_is_html_escaped(self):
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            1,
            "<b>bold</b> & risky",
            1,
            _reservation(),
            AttendanceStatus.ATTENDED.value,
        )
        assert "&lt;b&gt;bold&lt;/b&gt; &amp; risky" in text

    def test_an_unknown_status_omits_the_outcome_line(self):
        """Rather than emit a blank or wrong line for a value it cannot read."""
        text = ScoreNotificationService._format(
            ScoreTransactionType.ATTENDANCE_SCORE.value,
            1,
            "Reason",
            1,
            _reservation(),
            "something_else",
        )
        assert "You attended" not in text
        assert "not having attended" not in text
        assert "You received <b>+1</b> point(s)!" in text

    def test_a_non_attendance_type_never_shows_an_outcome_line(self):
        text = ScoreNotificationService._format(
            ScoreTransactionType.NO_SHOW_PENALTY.value,
            -1,
            "Legacy penalty",
            1,
            _reservation(),
        )
        assert "You attended" not in text
        assert "<b>Score Update</b>" in text
