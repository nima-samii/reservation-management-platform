"""Pure unit tests for recurrence next-run computation (no DB)."""
from datetime import datetime, timezone

import pytest

from app.services.recurrence import compute_next_run

# 2026-06-18 is a Thursday (weekday()==3)
NOW = datetime(2026, 6, 18, 10, 0, tzinfo=timezone.utc)


def test_daily():
    assert compute_next_run(frequency="daily", interval=1, day_of_week=None, day_of_month=None, after=NOW) == datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc)


def test_daily_interval():
    assert compute_next_run(frequency="daily", interval=3, day_of_week=None, day_of_month=None, after=NOW) == datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)


def test_weekly_to_monday():
    # next Monday after Thu 18th is the 22nd
    assert compute_next_run(frequency="weekly", interval=1, day_of_week=0, day_of_month=None, after=NOW) == datetime(2026, 6, 22, 10, 0, tzinfo=timezone.utc)


def test_weekly_interval_two():
    assert compute_next_run(frequency="weekly", interval=2, day_of_week=0, day_of_month=None, after=NOW) == datetime(2026, 6, 29, 10, 0, tzinfo=timezone.utc)


def test_monthly_day_already_passed_rolls_forward():
    # day 1 has passed in June → July 1
    assert compute_next_run(frequency="monthly", interval=1, day_of_week=None, day_of_month=1, after=NOW) == datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)


def test_monthly_day_future_same_month():
    assert compute_next_run(frequency="monthly", interval=1, day_of_week=None, day_of_month=25, after=NOW) == datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc)


def test_monthly_clamps_to_month_length():
    # day 31 in June (30 days) clamps to the 30th
    assert compute_next_run(frequency="monthly", interval=1, day_of_week=None, day_of_month=31, after=NOW) == datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc)


def test_yearly_rejected():
    with pytest.raises(ValueError):
        compute_next_run(frequency="yearly", interval=1, day_of_week=None, day_of_month=None, after=NOW)


# ── Time-of-day (hour/minute) selection ───────────────────────────────────────

def test_daily_time_ahead_today_fires_today():
    # NOW is 10:00; a 14:30 daily run should fire TODAY at 14:30
    assert compute_next_run(
        frequency="daily", interval=1, day_of_week=None, day_of_month=None,
        after=NOW, hour=14, minute=30,
    ) == datetime(2026, 6, 18, 14, 30, tzinfo=timezone.utc)


def test_daily_time_passed_rolls_to_tomorrow():
    # NOW is 10:00; an 08:00 daily run already passed → tomorrow 08:00
    assert compute_next_run(
        frequency="daily", interval=1, day_of_week=None, day_of_month=None,
        after=NOW, hour=8, minute=0,
    ) == datetime(2026, 6, 19, 8, 0, tzinfo=timezone.utc)


def test_daily_time_interval_three_rolls_forward():
    # 08:00 passed today, interval 3 → +3 days at 08:00
    assert compute_next_run(
        frequency="daily", interval=3, day_of_week=None, day_of_month=None,
        after=NOW, hour=8, minute=0,
    ) == datetime(2026, 6, 21, 8, 0, tzinfo=timezone.utc)


def test_weekly_time_pins_hour_minute():
    # next Monday at 09:15 regardless of NOW's 10:00
    assert compute_next_run(
        frequency="weekly", interval=1, day_of_week=0, day_of_month=None,
        after=NOW, hour=9, minute=15,
    ) == datetime(2026, 6, 22, 9, 15, tzinfo=timezone.utc)


def test_monthly_time_pins_hour_minute():
    assert compute_next_run(
        frequency="monthly", interval=1, day_of_week=None, day_of_month=25,
        after=NOW, hour=20, minute=0,
    ) == datetime(2026, 6, 25, 20, 0, tzinfo=timezone.utc)
