"""Tests for `was_absent` — pure, no DB.

Two mechanisms can record that a session was missed, and both are authoritative
for the rows they wrote:

  * ``reservations.attendance_status = 'absent'`` — the current decision
  * ``notes["no_show_penalty_applied"]``          — the retired penalty flag

Every counter, filter and export that reports absences reads through this one
function, so these tests are what stop the dashboard, the day summary, the
export and the broadcast segments from disagreeing with each other.
"""
import json

import pytest

from app.db.models.reservation import AttendanceStatus
from app.repositories.reservation import was_absent


# ── The current system ────────────────────────────────────────────────────────

def test_an_absent_decision_counts():
    assert was_absent(AttendanceStatus.ABSENT.value, None) is True


def test_an_attended_decision_does_not():
    assert was_absent(AttendanceStatus.ATTENDED.value, None) is False


def test_no_decision_yet_does_not():
    """NULL means "nobody has judged this session", which is not an absence.
    Counting it as one would report every future reservation as missed."""
    assert was_absent(None, None) is False


# ── The retired system ────────────────────────────────────────────────────────

def test_the_legacy_flag_counts():
    notes = json.dumps({"no_show_penalty_applied": True})
    assert was_absent(None, notes) is True


def test_the_legacy_flag_is_read_from_real_serialized_notes():
    """The flag was merged into whatever `notes` already held, so it is rarely
    the only key — the check has to survive that."""
    notes = json.dumps(
        {"original_notes": "booked via bot", "no_show_penalty_applied": True}
    )
    assert was_absent(None, notes) is True


@pytest.mark.parametrize(
    "notes",
    [
        None,
        "",
        "not json at all",
        "{}",
        json.dumps({"no_show_penalty_applied": False}),
        json.dumps({"something_else": True}),
    ],
)
def test_notes_without_a_set_flag_do_not_count(notes):
    assert was_absent(None, notes) is False


# ── Both at once ──────────────────────────────────────────────────────────────

def test_the_two_systems_do_not_double_count_into_disagreement():
    """A row carrying both is still one absence. It should not exist — the
    endpoints refuse each other — but the answer has to be stable if it does."""
    notes = json.dumps({"no_show_penalty_applied": True})
    assert was_absent(AttendanceStatus.ABSENT.value, notes) is True


def test_an_attended_decision_does_not_erase_a_legacy_penalty():
    """The flag is history and cannot be revised; an `attended` decision on the
    same row would be a contradiction rather than a correction, so the absence
    is still reported. Reading it the other way would make a historical penalty
    vanish from the counters."""
    notes = json.dumps({"no_show_penalty_applied": True})
    assert was_absent(AttendanceStatus.ATTENDED.value, notes) is True
