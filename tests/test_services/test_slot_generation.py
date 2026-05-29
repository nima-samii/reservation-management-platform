"""Tests for SlotService._generate_slot_datetimes — pure datetime logic, no DB required."""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytz
import pytest

from app.services.slot import SlotService

TZ = pytz.timezone("Asia/Baghdad")
_TEST_DATE = date(2026, 5, 29)


def _make_service() -> SlotService:
    return SlotService(session=MagicMock())


def _dt(h: int, m: int) -> datetime:
    return TZ.localize(datetime(2026, 5, 29, h, m, 0))


# ── _generate_slot_datetimes ──────────────────────────────────────────────────

class TestGenerateSlotDatetimes:
    def setup_method(self):
        self.svc = _make_service()

    def test_normal_slots_start_at_configured_hour(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        first = slots[0]
        assert first.hour == 16 and first.minute == 0

    def test_normal_slots_use_30_minute_intervals(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        # Check first three intervals are 30 min apart
        for i in range(min(3, len(slots) - 1)):
            delta = slots[i + 1] - slots[i]
            assert delta.seconds == 1800

    def test_last_interval_slot_is_2330(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        # Interval slots stop at 23:30 (last slot before 23:59:59 barrier)
        interval_slots = [s for s in slots if not (s.hour == 23 and s.minute == 59)]
        assert interval_slots[-1].hour == 23
        assert interval_slots[-1].minute == 30

    def test_final_slot_2359_appended_when_enabled(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        final = slots[-1]
        assert final.hour == 23 and final.minute == 59

    def test_slots_are_chronologically_sorted(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        for i in range(len(slots) - 1):
            assert slots[i] < slots[i + 1]

    def test_final_slot_belongs_to_same_date(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        final = slots[-1]
        local_date = final.astimezone(TZ).date()
        assert local_date == _TEST_DATE

    def test_final_slot_not_duplicated(self):
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        count_2359 = sum(1 for s in slots if s.hour == 23 and s.minute == 59)
        assert count_2359 == 1

    def test_total_slot_count_with_final_slot(self):
        # 16:00–23:30 → 16 slots (8 hours × 2) + 1 final = 17
        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        assert len(slots) == 17

    @patch("app.services.slot.settings")
    def test_no_final_slot_when_disabled(self, mock_settings):
        mock_settings.SLOT_START_HOUR = 16
        mock_settings.SLOT_END_HOUR = 24
        mock_settings.SLOT_DURATION_MINUTES = 30
        mock_settings.ENABLE_FINAL_MIDNIGHT_SLOT = False
        mock_settings.FINAL_SLOT_TIME = "23:59"

        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        assert not any(s.hour == 23 and s.minute == 59 for s in slots)

    @patch("app.services.slot.settings")
    def test_total_slot_count_without_final_slot(self, mock_settings):
        mock_settings.SLOT_START_HOUR = 16
        mock_settings.SLOT_END_HOUR = 24
        mock_settings.SLOT_DURATION_MINUTES = 30
        mock_settings.ENABLE_FINAL_MIDNIGHT_SLOT = False
        mock_settings.FINAL_SLOT_TIME = "23:59"

        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        assert len(slots) == 16

    @patch("app.services.slot.settings")
    def test_no_duplicate_if_final_slot_time_matches_interval(self, mock_settings):
        """If FINAL_SLOT_TIME coincides with a normal interval slot, it must not be duplicated."""
        mock_settings.SLOT_START_HOUR = 16
        mock_settings.SLOT_END_HOUR = 24
        mock_settings.SLOT_DURATION_MINUTES = 30
        mock_settings.ENABLE_FINAL_MIDNIGHT_SLOT = True
        mock_settings.FINAL_SLOT_TIME = "23:30"  # already in interval range

        slots = self.svc._generate_slot_datetimes(_TEST_DATE)
        count_2330 = sum(1 for s in slots if s.hour == 23 and s.minute == 30)
        assert count_2330 == 1


# ── _slots_per_day ────────────────────────────────────────────────────────────

class TestSlotsPerDay:
    def setup_method(self):
        self.svc = _make_service()

    def test_count_includes_final_slot_when_enabled(self):
        # default settings: 16 interval + 1 final = 17
        assert self.svc._slots_per_day() == 17

    @patch("app.services.slot.settings")
    def test_count_excludes_final_slot_when_disabled(self, mock_settings):
        mock_settings.SLOT_START_HOUR = 16
        mock_settings.SLOT_END_HOUR = 24
        mock_settings.SLOT_DURATION_MINUTES = 30
        mock_settings.ENABLE_FINAL_MIDNIGHT_SLOT = False

        assert self.svc._slots_per_day() == 16


# ── _parse_final_slot_time ────────────────────────────────────────────────────

class TestParseFinalSlotTime:
    def setup_method(self):
        self.svc = _make_service()

    def test_parses_2359(self):
        assert self.svc._parse_final_slot_time() == (23, 59)

    @patch("app.services.slot.settings")
    def test_parses_custom_time(self, mock_settings):
        mock_settings.FINAL_SLOT_TIME = "22:45"
        assert self.svc._parse_final_slot_time() == (22, 45)
