"""The Telegram side of SEQUENTIAL_FILL: logical ``lslot:HH:MM`` buttons.

Two things are pinned here, and the second matters more than the first:

* the keyboard emits whichever callback form the configured strategy can
  actually resolve, and the ``lslot`` handler round-trips it back to the same
  instant;
* ``slot:{uuid}`` keeps working. A keyboard already sitting in a chat cannot be
  re-rendered, so every strategy switch leaves both forms live in the wild for
  as long as those messages exist.
"""
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from app.bot.handlers.reservation import (
    _slot_ref_from_state,
    choose_logical_slot,
    choose_slot,
)
from app.bot.keyboards.inline.slots import build_slot_keyboard_grouped
from app.core.config import settings

TZ = pytz.timezone(settings.TIMEZONE)


def _slot(hour: int, minute: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        slot_datetime=TZ.localize(datetime(2030, 6, 1, hour, minute)),
    )


def _callbacks(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _labels(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


# ── keyboard ──────────────────────────────────────────────────────────────────

class TestKeyboard:
    def test_identity_mode_is_unchanged(self):
        """THRESHOLD_UNLOCK's keyboard must be byte-identical to before logical
        callbacks existed — same ids, same two section headers."""
        rec, more = [_slot(16)], [_slot(17)]

        markup = build_slot_keyboard_grouped(rec, more)

        assert f"slot:{rec[0].id}" in _callbacks(markup)
        assert f"slot:{more[0].id}" in _callbacks(markup)
        assert "📌 Recommended Slots" in _labels(markup)
        assert "➕ More Available Slots" in _labels(markup)

    def test_by_time_mode_names_the_hour_not_the_row(self):
        slots = [_slot(16), _slot(23, 59)]

        markup = build_slot_keyboard_grouped(slots, [], by_time=True)

        assert "lslot:16:00" in _callbacks(markup)
        assert "lslot:23:59" in _callbacks(markup)
        assert not any(c.startswith("slot:") for c in _callbacks(markup))

    def test_by_time_callbacks_are_24_hour(self):
        """The visible label is 12-hour. 6 PM and 6 AM must not collide in the
        callback the way they would if the label were reused."""
        markup = build_slot_keyboard_grouped([_slot(18), _slot(6)], [], by_time=True)

        assert "lslot:18:00" in _callbacks(markup)
        assert "lslot:06:00" in _callbacks(markup)

    def test_by_time_mode_drops_the_channel_section_headers(self):
        """"Recommended" implies something to be recommended *over*. Under a
        by-time strategy the user never chooses a channel, so there is no second
        section and the header would describe a distinction that does not
        exist."""
        markup = build_slot_keyboard_grouped([_slot(16)], [], by_time=True)

        assert "📌 Recommended Slots" not in _labels(markup)
        assert not any(c.startswith("section:") for c in _callbacks(markup))

    def test_both_modes_keep_the_back_and_cancel_row(self):
        for by_time in (False, True):
            markup = build_slot_keyboard_grouped([_slot(16)], [], by_time=by_time)
            assert "reservation:back_to_dates" in _callbacks(markup)
            assert "reservation:cancel" in _callbacks(markup)

    def test_callback_data_stays_within_telegram_limit(self):
        """Telegram rejects callback_data over 64 bytes. Cheap to assert, and
        the failure mode is a keyboard Telegram refuses to render at all."""
        markup = build_slot_keyboard_grouped(
            [_slot(16)], [_slot(17)], by_time=False
        )
        for data in _callbacks(markup):
            assert len(data.encode()) <= 64, data


# ── FSM reference recovery ────────────────────────────────────────────────────

class TestSlotRefFromState:
    def test_reads_a_stored_time(self):
        when = TZ.localize(datetime(2030, 6, 1, 18, 0))

        assert _slot_ref_from_state({"slot_time": when.isoformat()}) == when

    def test_reads_a_stored_uuid(self):
        slot_id = uuid.uuid4()

        assert _slot_ref_from_state({"slot_id": str(slot_id)}) == slot_id

    def test_an_in_flight_session_from_before_this_release_still_resolves(self):
        """A user mid-flow across a deploy has only `slot_id` in their FSM. It
        must keep working rather than becoming an expired session."""
        slot_id = uuid.uuid4()

        assert _slot_ref_from_state({"slot_id": str(slot_id), "selected_date": "2030-06-01"}) == slot_id

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"slot_id": "not-a-uuid"},
            {"slot_time": "not-a-datetime"},
            {"slot_id": None, "slot_time": None},
        ],
    )
    def test_unusable_state_is_reported_as_no_reference(self, data):
        assert _slot_ref_from_state(data) is None


# ── handlers ──────────────────────────────────────────────────────────────────

def _callback(data: str):
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    return cb


def _state(data: dict):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


USER = SimpleNamespace(telegram_id=1, id=uuid.uuid4())


class TestLogicalSlotHandler:
    @pytest.mark.asyncio
    async def test_stores_the_tapped_time_against_the_chosen_date(self):
        state = _state({"selected_date": "2030-06-01"})

        await choose_logical_slot(_callback("lslot:18:30"), state, USER)

        stored = state.update_data.await_args.kwargs
        assert stored["slot_time"] == TZ.localize(datetime(2030, 6, 1, 18, 30)).isoformat()
        # The other form is cleared, so a leftover id from an earlier tap can
        # never be picked up instead of the time just chosen.
        assert stored["slot_id"] is None

    @pytest.mark.asyncio
    async def test_the_stored_value_round_trips_to_the_same_instant(self):
        """This is the contract the booking depends on: the time in the FSM has
        to equal the slot_datetime in the database, to the second."""
        state = _state({"selected_date": "2030-06-01"})

        await choose_logical_slot(_callback("lslot:23:59"), state, USER)

        recovered = _slot_ref_from_state(state.update_data.await_args.kwargs)
        assert recovered == TZ.localize(datetime(2030, 6, 1, 23, 59, 0))
        assert recovered.utcoffset() is not None, "must stay timezone-aware"

    @pytest.mark.asyncio
    async def test_shows_the_summary_and_advances_to_confirm(self):
        state = _state({"selected_date": "2030-06-01"})
        callback = _callback("lslot:18:00")

        await choose_logical_slot(callback, state, USER)

        text = callback.message.edit_text.await_args.args[0]
        assert "06:00 PM" in text
        state.set_state.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["lslot:99:00", "lslot:noon", "lslot:18", "lslot:"])
    async def test_a_malformed_time_expires_the_session_instead_of_raising(self, data):
        state = _state({"selected_date": "2030-06-01"})
        callback = _callback(data)

        await choose_logical_slot(callback, state, USER)

        state.update_data.assert_not_awaited()
        state.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_missing_date_expires_the_session(self):
        """Unreachable through the normal flow — the state filter guarantees
        choose_date ran — so if it happens the session really is broken, and
        guessing a date would book the wrong day."""
        state = _state({})

        await choose_logical_slot(_callback("lslot:18:00"), state, USER)

        state.update_data.assert_not_awaited()
        state.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_an_unregistered_user_is_turned_away(self):
        state = _state({"selected_date": "2030-06-01"})

        await choose_logical_slot(_callback("lslot:18:00"), state, None)

        state.update_data.assert_not_awaited()


class TestLegacySlotHandler:
    @pytest.mark.asyncio
    async def test_a_uuid_button_still_books_that_row(self):
        """The legacy form, still live under THRESHOLD_UNLOCK and still honoured
        under SEQUENTIAL_FILL."""
        slot = _slot(18)
        state = _state({"selected_date": "2030-06-01"})
        callback = _callback(f"slot:{slot.id}")

        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=slot)
        with patch("app.bot.handlers.reservation.SlotRepository", return_value=repo):
            await choose_slot(callback, state, MagicMock(), USER)

        stored = state.update_data.await_args.kwargs
        assert stored["slot_id"] == str(slot.id)
        assert stored["slot_time"] is None
        assert "06:00 PM" in callback.message.edit_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_a_deleted_slot_is_reported_before_the_summary(self):
        state = _state({"selected_date": "2030-06-01"})
        callback = _callback(f"slot:{uuid.uuid4()}")

        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=None)
        with patch("app.bot.handlers.reservation.SlotRepository", return_value=repo):
            await choose_slot(callback, state, MagicMock(), USER)

        state.update_data.assert_not_awaited()
        callback.message.edit_text.assert_not_awaited()


# ── the keyboard and the booking path cannot disagree ─────────────────────────

@pytest.mark.parametrize("by_time", [False, True])
def test_every_emitted_callback_is_parseable_back_into_a_reference(by_time):
    """The end-to-end invariant behind both formats: whatever the keyboard puts
    in a button, the FSM must be able to hand back to the booking. A format
    added to one side and not the other fails here rather than in production."""
    slots = [_slot(16), _slot(23, 59)]
    markup = build_slot_keyboard_grouped(slots, [], by_time=by_time)

    taps = [c for c in _callbacks(markup) if c.startswith(("slot:", "lslot:"))]
    assert len(taps) == len(slots)

    for data in taps:
        prefix, _, payload = data.partition(":")
        if prefix == "lslot":
            hour, minute = (int(p) for p in payload.split(":", 1))
            stored = {"slot_time": TZ.localize(
                datetime(2030, 6, 1, hour, minute)
            ).isoformat()}
        else:
            stored = {"slot_id": payload}

        ref = _slot_ref_from_state(stored)
        assert ref is not None
        assert isinstance(ref, (uuid.UUID, datetime))
