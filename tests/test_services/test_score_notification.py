"""Tests for ScoreNotificationService._format — pure, no DB.

Covers the message body:
  * sign-aware headline (gain vs loss)
  * reason line + current score always present
  * linked-reservation details (date/time/channel) appended when provided,
    e.g. for a no-show penalty
"""
from datetime import datetime, timezone
from types import SimpleNamespace

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
