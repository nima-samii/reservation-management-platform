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

    def test_the_automatic_deltas_survived_the_rewrite(self):
        # These are what the bot actually does on its own — see _SCORE_POLICY in
        # services/score.py. Dropping them for the new rules would leave the
        # screen silent about the only score changes users see day to day.
        text = build_help_text()
        assert "*+1* when you successfully reserve a session" in text
        assert "*−1* if you cancel a reservation" in text

    def test_the_no_show_penalty_is_stated_as_real(self):
        # apply_no_show_penalty is implemented and admin-triggered, so the old
        # "future penalties may apply" hedge was untrue.
        text = build_help_text()
        assert "Future penalties" not in text
        assert "don't attend a session you booked" in text


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
