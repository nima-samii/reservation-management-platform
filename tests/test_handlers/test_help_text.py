"""Tests for the help screen text.

This screen is one long hand-written string sent with ``parse_mode="Markdown"``.
Telegram's legacy Markdown parser is all-or-nothing: a single unpaired ``*``
does not italicise the wrong word, it makes the API reject the message and the
Help button stops working entirely. Nothing else in the code would notice, so
the balance is asserted here.
"""
import pytest

from app.bot.handlers.help import build_help_text
from app.core.config import settings


@pytest.fixture
def restore_settings():
    original = {
        "MAX_DAILY_RESERVATIONS": settings.MAX_DAILY_RESERVATIONS,
        "MAX_ACTIVE_RESERVATIONS": settings.MAX_ACTIVE_RESERVATIONS,
    }
    yield
    for key, value in original.items():
        object.__setattr__(settings, key, value)


# ── Telegram will accept it ───────────────────────────────────────────────────

class TestMarkdownIsWellFormed:
    def test_bold_markers_are_paired(self):
        assert build_help_text().count("*") % 2 == 0

    def test_no_stray_underscores(self):
        # Legacy Markdown reads `_` as italic. There is no italic text on this
        # screen, so any underscore at all is an unpaired one.
        assert "_" not in build_help_text()

    def test_no_stray_backticks_or_brackets(self):
        text = build_help_text()
        assert text.count("`") % 2 == 0
        assert "[" not in text

    def test_fits_in_one_telegram_message(self):
        assert len(build_help_text()) <= 4096


# ── Score Calculation System ──────────────────────────────────────────────────

class TestScoreCalculationSystem:
    def test_all_four_earning_rules_are_listed(self):
        text = build_help_text()
        assert "number of participants in each live broadcast" in text
        assert "30 points" in text
        assert "your points are doubled" in text
        assert "number of participants in the course" in text

    def test_the_admin_awarded_rules_say_who_awards_them(self):
        # Without this line the four rules read as things the bot computes, and
        # a user who hosts a broadcast waits for a score that never moves.
        assert "awarded by an admin" in build_help_text()

    def test_no_automatic_delta_is_promised_any_more(self):
        # Booking and cancelling stopped moving the score, so the old "+1 when
        # you reserve" / "−1 if you cancel" lines became false promises. A user
        # who reads them waits for a change that never comes.
        text = build_help_text()
        assert "+1" not in text
        assert "−1" not in text
        assert "-1" not in text

    def test_booking_and_cancelling_are_stated_as_score_neutral(self):
        # Stating it is the point: the previous screen promised deltas, so
        # silence would read as the old behaviour still applying.
        text = build_help_text()
        assert "Booking a session does not change your score" in text
        assert "Cancelling a session does not change your score" in text

    def test_the_screen_explains_who_decides_and_that_a_note_comes_with_it(self):
        # The score is now an admin decision per session, carrying an
        # explanation the user is sent. Without this the four earning rules
        # above read as things the bot computes.
        text = build_help_text()
        assert "An admin reviews the session" in text
        assert "explaining the decision" in text

    def test_the_old_no_show_penalty_is_no_longer_described(self):
        # Absence no longer means a fixed -1: it is one of two outcomes an
        # admin records, and the score attached to it is theirs to choose.
        text = build_help_text()
        assert "Future penalties" not in text
        assert "don't attend a session you booked" not in text


# ── The caps are still read at render time ────────────────────────────────────

class TestConfigurableCaps:
    def test_a_cap_of_one_reads_as_one(self, restore_settings):
        object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", 1)
        assert "• One reservation per day" in build_help_text()

    def test_a_higher_cap_reads_as_a_number(self, restore_settings):
        object.__setattr__(settings, "MAX_DAILY_RESERVATIONS", 3)
        assert "• Up to 3 reservations per day" in build_help_text()

    def test_the_active_cap_is_not_frozen_at_import(self, restore_settings):
        object.__setattr__(settings, "MAX_ACTIVE_RESERVATIONS", 7)
        assert "Max 7 active reservations" in build_help_text()
