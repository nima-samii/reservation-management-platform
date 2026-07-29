"""Tests for SlotService._generate_slot_datetimes — pure datetime logic, no DB required."""
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── get_available_slots_for_date_grouped (channel-unlock threshold) ────────────

class TestChannelUnlockThreshold:
    """The next channel unlocks only when the current channel's fill ratio
    reaches CHANNEL_CAPACITY_THRESHOLD. The denominator MUST be the real
    per-channel/day generated slot count (repo), NOT the settings-derived
    _slots_per_day() — otherwise changing SLOT_* settings after generation
    shrinks the denominator and unlocks later channels far too early.
    """

    # Far-future date so the same-day cutoff never interferes.
    FUTURE = date(2099, 1, 1)

    def _svc_with_channels(self, n: int) -> SlotService:
        svc = SlotService(session=MagicMock())
        channels = [SimpleNamespace(id=uuid.uuid4()) for _ in range(n)]
        svc._channel_repo.get_active_channels_ordered = AsyncMock(return_value=channels)
        return svc

    @pytest.mark.asyncio
    @patch("app.services.slot.settings")
    async def test_next_channel_locked_when_below_threshold(self, mock_settings):
        # Exactly the reported symptom: channel 0 at 3/19 (16%) < 70%.
        mock_settings.CHANNEL_CAPACITY_THRESHOLD = 0.70
        mock_settings.SAME_DAY_CUTOFF_HOUR = "12:00"
        svc = self._svc_with_channels(2)

        ch0_slots = ["ch0-slot"]
        svc._repo.get_available_slots_for_date_and_channel = AsyncMock(
            side_effect=[ch0_slots]
        )
        svc._channel_repo.get_reservation_count_for_date = AsyncMock(side_effect=[3])
        svc._repo.count_slots_for_date_and_channel = AsyncMock(side_effect=[19])

        grouped = await svc.get_available_slots_for_date_grouped(self.FUTURE)

        assert grouped["recommended"] == ch0_slots
        assert grouped["more_available"] == []  # channel 1 stayed locked
        # Loop must break before ever querying channel 1.
        assert svc._repo.get_available_slots_for_date_and_channel.await_count == 1

    @pytest.mark.asyncio
    @patch("app.services.slot.settings")
    async def test_denominator_uses_real_capacity_not_settings(self, mock_settings):
        # Real capacity 4 → 3/4 = 75% ≥ 70% unlocks channel 1, even though the
        # settings-derived _slots_per_day() (=17) would say 3/17 < 70% locked.
        mock_settings.CHANNEL_CAPACITY_THRESHOLD = 0.70
        mock_settings.SAME_DAY_CUTOFF_HOUR = "12:00"
        svc = self._svc_with_channels(2)
        # Guarantee the gate no longer consults the settings-derived helper.
        svc._slots_per_day = MagicMock(
            side_effect=AssertionError("_slots_per_day() must not gate unlocking")
        )

        ch0_slots, ch1_slots = ["ch0-slot"], ["ch1-slot"]
        svc._repo.get_available_slots_for_date_and_channel = AsyncMock(
            side_effect=[ch0_slots, ch1_slots]
        )
        svc._channel_repo.get_reservation_count_for_date = AsyncMock(side_effect=[3, 0])
        svc._repo.count_slots_for_date_and_channel = AsyncMock(side_effect=[4, 19])

        grouped = await svc.get_available_slots_for_date_grouped(self.FUTURE)

        assert grouped["recommended"] == ch0_slots
        assert grouped["more_available"] == ch1_slots  # unlocked via real capacity

    @pytest.mark.asyncio
    @patch("app.services.slot.settings")
    async def test_zero_capacity_channel_unlocks_next(self, mock_settings):
        # A channel with no slots generated that day must not strand the user:
        # it is treated as "full" so the next channel still unlocks.
        mock_settings.CHANNEL_CAPACITY_THRESHOLD = 0.70
        mock_settings.SAME_DAY_CUTOFF_HOUR = "12:00"
        svc = self._svc_with_channels(2)

        ch1_slots = ["ch1-slot"]
        svc._repo.get_available_slots_for_date_and_channel = AsyncMock(
            side_effect=[[], ch1_slots]
        )
        svc._channel_repo.get_reservation_count_for_date = AsyncMock(side_effect=[0, 0])
        svc._repo.count_slots_for_date_and_channel = AsyncMock(side_effect=[0, 19])

        grouped = await svc.get_available_slots_for_date_grouped(self.FUTURE)

        assert grouped["recommended"] == []
        assert grouped["more_available"] == ch1_slots
