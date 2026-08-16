"""Tests for ScheduleFormatter — pure rendering logic, no DB required."""
from datetime import datetime, date, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytz

from app.services.schedule_formatter import (
    ScheduleFormatter,
    clock_emoji_for,
    display_name_for,
    format_time,
    _CLOCK_EMOJI,
    _GENDER_EMOJI,
    _MAX_NAME_LEN,
)

TZ = pytz.timezone("Asia/Baghdad")


def _make_slot(hour: int, minute: int = 0):
    naive = datetime(2026, 5, 29, hour, minute)
    return SimpleNamespace(slot_datetime=TZ.localize(naive))


def _make_user(
    gender=None, country_name="Malaysia", flag="🇲🇾", score=10, code="ABC123", name="Nima"
):
    country = SimpleNamespace(name=country_name, flag_emoji=flag) if country_name else None
    return SimpleNamespace(
        gender=gender,
        country_rel=country,
        participation_score=score,
        public_user_code=code,
        full_name=name,
    )


def _make_reservation(
    hour,
    minute=0,
    gender="female",
    country="Malaysia",
    flag="🇲🇾",
    score=10,
    code="ABC",
    name="Nima",
):
    return SimpleNamespace(
        user=_make_user(
            gender=gender,
            country_name=country,
            flag=flag,
            score=score,
            code=code,
            name=name,
        ),
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


# ── display_name_for ───────────────────────────────────────────────────────────

class TestDisplayNameFor:
    """The one free-text field in the broadcast that the user wrote themselves."""

    def test_a_plain_name_passes_through(self):
        assert display_name_for("Nima") == "Nima"

    def test_surrounding_whitespace_is_dropped(self):
        assert display_name_for("  Nima  ") == "Nima"

    def test_angle_brackets_are_escaped(self):
        # Unescaped, this is not a cosmetic problem: Telegram rejects the whole
        # message and every other participant loses their row too.
        assert display_name_for("<b>Nima</b>") == "&lt;b&gt;Nima&lt;/b&gt;"

    def test_ampersand_is_escaped(self):
        assert display_name_for("Ali & Sons") == "Ali &amp; Sons"

    def test_an_apostrophe_is_left_alone(self):
        # quote=False — the name never lands in an attribute, and escaping here
        # would show O&#x27;Brien to every reader of the channel.
        assert display_name_for("O'Brien") == "O'Brien"

    def test_arabic_is_untouched(self):
        assert display_name_for("محمد") == "محمد"

    def test_a_long_name_is_truncated_with_an_ellipsis(self):
        result = display_name_for("A" * 100)
        assert len(result) == _MAX_NAME_LEN
        assert result.endswith("…")

    def test_a_name_at_the_limit_is_not_truncated(self):
        name = "B" * _MAX_NAME_LEN
        assert display_name_for(name) == name

    def test_truncation_counts_the_raw_name_not_the_escaped_one(self):
        # Escaping inflates length ~5x per character. Measuring after it would
        # cut a name of five ampersands down to one.
        assert display_name_for("&" * 5) == "&amp;" * 5

    def test_an_empty_name_is_empty(self):
        assert display_name_for("") == ""

    def test_a_whitespace_only_name_is_empty(self):
        assert display_name_for("   ") == ""

    def test_none_is_empty(self):
        assert display_name_for(None) == ""


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

    def test_name_and_code_render_together(self):
        reservations = [_make_reservation(16, 0, code="008735", name="Nima")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "<b>Nima</b> (<code>008735</code>)" in text

    def test_the_bare_id_label_is_gone(self):
        # The code is now identified by its position beside the name, so the
        # "ID:" prefix would just be noise on an already-crowded line.
        reservations = [_make_reservation(16, 0, code="008735")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "ID:" not in text

    def test_a_missing_name_falls_back_to_the_bare_code(self):
        # full_name is NOT NULL, so this is defence rather than a live path —
        # but empty parentheses would be worse than no parentheses.
        reservations = [_make_reservation(16, 0, code="008735", name="")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "<code>008735</code>" in text
        assert "()" not in text
        assert "<b></b>" not in text

    def test_a_name_with_markup_cannot_break_the_message(self):
        reservations = [_make_reservation(16, 0, name="<i>x</i>")]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "<i>x</i>" not in text
        assert "&lt;i&gt;x&lt;/i&gt;" in text

    def test_each_reservation_shows_its_own_name(self):
        reservations = [
            _make_reservation(16, 0, code="U001", name="Nima"),
            _make_reservation(16, 30, code="U002", name="Sara"),
        ]
        text = self.formatter.render(self.channel, self.today, reservations, [])
        assert "<b>Nima</b> (<code>U001</code>)" in text
        assert "<b>Sara</b> (<code>U002</code>)" in text

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
