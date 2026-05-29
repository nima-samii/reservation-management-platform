"""Tests for ScheduleFormatter — pure rendering logic, no DB required."""
from datetime import datetime, date, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytz

from app.services.schedule_formatter import (
    ScheduleFormatter,
    clock_emoji_for,
    format_time,
    _CLOCK_EMOJI,
    _GENDER_EMOJI,
)

TZ = pytz.timezone("Asia/Baghdad")


def _make_slot(hour: int, minute: int = 0):
    naive = datetime(2026, 5, 29, hour, minute)
    return SimpleNamespace(slot_datetime=TZ.localize(naive))


def _make_user(gender=None, country_name="Malaysia", flag="🇲🇾", score=10, code="ABC123"):
    country = SimpleNamespace(name=country_name, flag_emoji=flag) if country_name else None
    return SimpleNamespace(
        gender=gender,
        country_rel=country,
        participation_score=score,
        public_user_code=code,
    )


def _make_reservation(hour, minute=0, gender="female", country="Malaysia", flag="🇲🇾", score=10, code="ABC"):
    return SimpleNamespace(
        user=_make_user(gender=gender, country_name=country, flag=flag, score=score, code=code),
        slot=_make_slot(hour, minute),
    )


def _make_channel(name="Echoes", invite="https://t.me/+test"):
    return SimpleNamespace(name=name, invite_link=invite)


def _make_event(title="Collective Dhikr"):
    return SimpleNamespace(title=title)


# ── clock_emoji_for ────────────────────────────────────────────────────────────

class TestClockEmojiFor:
    def test_4pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 16, 0))
        assert clock_emoji_for(dt) == "🕓"

    def test_4_30pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 16, 30))
        assert clock_emoji_for(dt) == "🕟"

    def test_midnight(self):
        dt = TZ.localize(datetime(2026, 5, 30, 0, 0))
        assert clock_emoji_for(dt) == "🕛"

    def test_11_30pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 23, 30))
        assert clock_emoji_for(dt) == "🕦"

    def test_all_slot_times_have_emoji(self):
        # Slots run 16:00 – 23:30 in 30-min intervals
        for hour in range(16, 24):
            for minute in (0, 30):
                if hour == 24:
                    break
                dt = TZ.localize(datetime(2026, 5, 29, hour, minute))
                emoji = clock_emoji_for(dt)
                assert emoji != "⏰", f"No clock emoji for {hour}:{minute:02d}"


# ── format_time ────────────────────────────────────────────────────────────────

class TestFormatTime:
    def test_4pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 16, 0))
        assert format_time(dt) == "4:00 PM"

    def test_4_30pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 16, 30))
        assert format_time(dt) == "4:30 PM"

    def test_noon(self):
        dt = TZ.localize(datetime(2026, 5, 29, 12, 0))
        assert format_time(dt) == "12:00 PM"

    def test_midnight(self):
        dt = TZ.localize(datetime(2026, 5, 30, 0, 0))
        assert format_time(dt) == "12:00 AM"

    def test_11pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 23, 0))
        assert format_time(dt) == "11:00 PM"


# ── ScheduleFormatter.render ───────────────────────────────────────────────────

class TestScheduleFormatter:
    def setup_method(self):
        self.formatter = ScheduleFormatter()
        self.today = date(2026, 5, 29)
        self.channel = _make_channel()

    def test_renders_channel_name_in_header(self):
        text = self.formatter.render(self.channel, self.today, [], [])
        assert "Echoes" in text

    def test_renders_date_string(self):
        text = self.formatter.render(self.channel, self.today, [], [])
        assert "Friday, May 29, 2026" in text

    def test_renders_timezone_label(self):
        text = self.formatter.render(self.channel, self.today, [], [])
        assert "Asia/Baghdad" in text

    def test_empty_schedule_shows_no_sessions_message(self):
        text = self.formatter.render(self.channel, self.today, [], [])
        assert "No sessions" in text

    def test_reservation_time_appears(self):
        reservations = [_make_reservation(16, 0)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "4:00 PM" in text

    def test_reservation_clock_emoji_appears(self):
        reservations = [_make_reservation(16, 0)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "🕓" in text

    def test_reservation_user_code_in_code_tag(self):
        reservations = [_make_reservation(16, 0, code="ABC123")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "<code>ABC123</code>" in text

    def test_reservation_score_appears(self):
        reservations = [_make_reservation(16, 0, score=25)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "⭐ 25" in text

    def test_country_name_and_flag_appear(self):
        reservations = [_make_reservation(16, 0, country="Malaysia", flag="🇲🇾")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "Malaysia" in text
        assert "🇲🇾" in text

    def test_country_without_flag(self):
        reservations = [_make_reservation(16, 0, country="Iraq", flag=None)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "Iraq" in text

    def test_no_country_shows_dash(self):
        user = _make_user(gender="male", country_name=None, score=5, code="XY1")
        slot = _make_slot(17, 0)
        r = SimpleNamespace(user=user, slot=slot)
        text = self.formatter.render(self.channel, self.today, [r], [])
        assert "│" in text

    def test_female_gender_emoji(self):
        reservations = [_make_reservation(16, 0, gender="female")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "👩‍💼" in text

    def test_male_gender_emoji(self):
        reservations = [_make_reservation(16, 0, gender="male")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "👨‍💼" in text

    def test_not_say_gender_emoji(self):
        reservations = [_make_reservation(16, 0, gender="not_say")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "🧑‍💼" in text

    def test_event_title_appears(self):
        events = [_make_event("Collective Dhikr")]
        text = self.formatter.render(self.channel, self.today, [], events)
        assert "Collective Dhikr" in text

    def test_invite_link_rendered_as_html_anchor(self):
        text = self.formatter.render(self.channel, self.today, [], [])
        assert 'href="https://t.me/+test"' in text

    def test_no_invite_link_omitted(self):
        channel = _make_channel(invite=None)
        text = self.formatter.render(channel, self.today, [], [])
        assert "href=" not in text

    def test_multiple_reservations_all_appear(self):
        reservations = [
            _make_reservation(16, 0, code="U001"),
            _make_reservation(16, 30, code="U002"),
            _make_reservation(17, 0, code="U003"),
        ]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "U001" in text
        assert "U002" in text
        assert "U003" in text

    def test_2359_slot_formats_as_1159_pm(self):
        reservations = [_make_reservation(23, 59)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "11:59 PM" in text

    def test_2359_slot_clock_emoji(self):
        reservations = [_make_reservation(23, 59)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "🕦" in text

    def test_2359_no_next_day_rollover_in_output(self):
        reservations = [_make_reservation(23, 59)]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "12:00 AM" not in text
        assert "May 30" not in text


# ── clock_emoji_for: 23:59 special case ───────────────────────────────────────

class TestClockEmojiFor2359:
    def test_2359_returns_1130_emoji(self):
        dt = TZ.localize(datetime(2026, 5, 29, 23, 59))
        assert clock_emoji_for(dt) == "🕦"

    def test_2359_does_not_return_fallback(self):
        dt = TZ.localize(datetime(2026, 5, 29, 23, 59))
        assert clock_emoji_for(dt) != "⏰"


# ── format_time: 23:59 ────────────────────────────────────────────────────────

class TestFormatTime2359:
    def test_2359_formats_as_1159_pm(self):
        dt = TZ.localize(datetime(2026, 5, 29, 23, 59))
        assert format_time(dt) == "11:59 PM"
