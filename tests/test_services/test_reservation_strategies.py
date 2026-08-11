"""Tests for the Phase 2 strategy seam — mocked repos, no DB.

These pin the *seam*, not the threshold gate itself (that stays covered
unchanged by test_slot_generation.TestChannelUnlockThreshold):

  * THRESHOLD_UNLOCK resolves a booking to exactly the slot it was handed
  * the resolver honours RESERVATION_STRATEGY and fails loudly, never
    silently, for a strategy it cannot build
  * the admin path books the admin's chosen slot regardless of the
    configured strategy
"""
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import (
    RESERVATION_STRATEGY_SEQUENTIAL_FILL,
    RESERVATION_STRATEGY_THRESHOLD_UNLOCK,
)
from app.core.exceptions import (
    NotFoundError,
    SlotUnavailableError,
    UnsupportedReservationStrategyError,
)
from app.services.strategies.explicit import ExplicitSlotStrategy
from app.services.strategies.resolver import get_reservation_strategy
from app.services.strategies.sequential import SequentialFillStrategy
from app.services.strategies.threshold import ThresholdUnlockStrategy


def _slot(**kw) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), channel_id=uuid.uuid4(), **kw)


# ── resolver ──────────────────────────────────────────────────────────────────

class TestResolver:
    def _build(self, name=None):
        return get_reservation_strategy(
            slot_repo=MagicMock(), channel_repo=MagicMock(), name=name
        )

    def test_default_strategy_is_threshold_unlock(self):
        """No explicit name → whatever RESERVATION_STRATEGY says, which ships
        as THRESHOLD_UNLOCK."""
        strategy = self._build()
        assert isinstance(strategy, ThresholdUnlockStrategy)
        assert strategy.name == RESERVATION_STRATEGY_THRESHOLD_UNLOCK

    def test_sequential_fill_builds_its_own_strategy(self):
        """Never a silent fallback to THRESHOLD_UNLOCK. Before it was
        implemented this raised; now it must build the real thing — what must
        never happen is the resolver quietly returning the *other* strategy."""
        strategy = self._build(name=RESERVATION_STRATEGY_SEQUENTIAL_FILL)
        assert isinstance(strategy, SequentialFillStrategy)
        assert strategy.name == RESERVATION_STRATEGY_SEQUENTIAL_FILL

    def test_unknown_strategy_raises(self):
        with pytest.raises(UnsupportedReservationStrategyError):
            self._build(name="NOT_A_STRATEGY")

    def test_strategy_uses_the_repositories_it_was_given(self):
        """Repos are injected, not built from a session, so the strategy shares
        the caller's unit of work."""
        slot_repo, channel_repo = MagicMock(), MagicMock()
        strategy = get_reservation_strategy(
            slot_repo=slot_repo, channel_repo=channel_repo
        )
        assert strategy._repo is slot_repo
        assert strategy._channel_repo is channel_repo


# ── resolution seam ───────────────────────────────────────────────────────────

class TestExplicitResolution:
    @pytest.mark.asyncio
    async def test_returns_the_locked_slot(self):
        slot = _slot()
        repo = AsyncMock()
        repo.get_slot_with_lock = AsyncMock(return_value=slot)

        assert await ExplicitSlotStrategy(repo).resolve_slot(slot.id) is slot
        repo.get_slot_with_lock.assert_awaited_once_with(slot.id)

    @pytest.mark.asyncio
    async def test_lock_contention_becomes_slot_unavailable(self):
        # FOR UPDATE NOWAIT raises OperationalError when another booking holds
        # the row; the user must see "unavailable", not a 500.
        repo = AsyncMock()
        repo.get_slot_with_lock = AsyncMock(
            side_effect=OperationalError("SELECT ...", {}, Exception("locked"))
        )

        with pytest.raises(SlotUnavailableError):
            await ExplicitSlotStrategy(repo).resolve_slot(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_missing_slot_raises_not_found(self):
        repo = AsyncMock()
        repo.get_slot_with_lock = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await ExplicitSlotStrategy(repo).resolve_slot(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_threshold_unlock_resolves_by_identity(self):
        """THRESHOLD_UNLOCK renders one button per physical slot, so booking
        must claim that exact slot — no channel substitution."""
        slot = _slot()
        repo = AsyncMock()
        repo.get_slot_with_lock = AsyncMock(return_value=slot)
        strategy = ThresholdUnlockStrategy(slot_repo=repo, channel_repo=MagicMock())

        resolved = await strategy.resolve_slot(slot.id)

        assert resolved is slot
        assert resolved.channel_id == slot.channel_id


# ── SEQUENTIAL_FILL ───────────────────────────────────────────────────────────

class TestSequentialFill:
    """The row-level race is covered against a real server in
    tests/test_repositories/test_slot_priority_lock.py. These cover the
    strategy's own decisions: what it asks the repository for, and how it
    translates the answers."""

    def _strategy(self, repo):
        return SequentialFillStrategy(slot_repo=repo)

    @pytest.mark.asyncio
    async def test_resolves_by_time_not_by_the_tapped_row(self):
        """The tapped slot names a *time*. The booking may well land on a
        different channel — that is the whole strategy."""
        tapped = _slot(slot_datetime="18:00")
        winner = _slot()
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=tapped)
        repo.lock_next_slot_by_priority = AsyncMock(return_value=winner)

        resolved = await self._strategy(repo).resolve_slot(tapped.id)

        assert resolved is winner
        assert resolved.channel_id != tapped.channel_id
        repo.lock_next_slot_by_priority.assert_awaited_once_with("18:00")

    @pytest.mark.asyncio
    async def test_does_not_lock_the_representative_row(self):
        """Locking the tapped row would hold a slot the booking is not going to
        claim, blocking a booker the database could have served."""
        tapped = _slot(slot_datetime="18:00")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=tapped)
        repo.lock_next_slot_by_priority = AsyncMock(return_value=_slot())

        await self._strategy(repo).resolve_slot(tapped.id)

        repo.get_slot_with_lock.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_free_channel_becomes_slot_unavailable(self):
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=_slot(slot_datetime="18:00"))
        repo.lock_next_slot_by_priority = AsyncMock(return_value=None)

        with pytest.raises(SlotUnavailableError):
            await self._strategy(repo).resolve_slot(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_missing_tapped_slot_raises_not_found(self):
        """A stale keyboard naming a deleted slot must not be resolved to some
        other row that happens to share nothing with it."""
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await self._strategy(repo).resolve_slot(uuid.uuid4())

        repo.lock_next_slot_by_priority.assert_not_called()

    @pytest.mark.asyncio
    async def test_listing_offers_each_time_once_with_no_second_section(self):
        slots = [_slot(), _slot()]
        repo = AsyncMock()
        repo.get_distinct_open_slots_for_date = AsyncMock(return_value=slots)

        grouped = await self._strategy(repo).list_bookable_slots(
            date(2030, 6, 1), now="NOW"
        )

        assert grouped["recommended"] == slots
        # There is no "additional channels" section: the user never picks one.
        assert grouped["more_available"] == []
        repo.get_distinct_open_slots_for_date.assert_awaited_once_with(
            date(2030, 6, 1), "NOW"
        )

    @pytest.mark.asyncio
    async def test_listing_never_consults_the_capacity_threshold(self):
        """CHANNEL_CAPACITY_THRESHOLD is meaningless here — reading it would
        make the panel's "ignored under Sequential fill" hint a lie. A config
        that explodes on *any* attribute read proves it is never touched."""

        class Forbidden:
            def __getattr__(self, name):
                raise AssertionError(f"read settings.{name} under SEQUENTIAL_FILL")

        repo = AsyncMock()
        repo.get_distinct_open_slots_for_date = AsyncMock(return_value=[])

        strategy = SequentialFillStrategy(slot_repo=repo, config=Forbidden())
        assert await strategy.list_bookable_slots(date(2030, 6, 1), now="NOW")


# ── advisory-lock policy ──────────────────────────────────────────────────────

class TestContentionKey:
    """Which Redis key ``_book`` serialises on. Getting this wrong does not
    crash — it silently rejects valid bookings — so it is pinned directly."""

    USER = uuid.uuid4()
    SLOT = uuid.uuid4()

    def _key(self, strategy, user=None):
        from app.services.reservation import ReservationService

        return ReservationService._contended_resource(
            user or self.USER, self.SLOT, strategy
        )

    def test_identity_resolution_locks_the_slot_id_unchanged(self):
        """Pre-strategy behaviour, unchanged: two users tapping the same slot
        contend for it, and one is turned away."""
        threshold = ThresholdUnlockStrategy(
            slot_repo=AsyncMock(), channel_repo=MagicMock()
        )

        assert self._key(None) == str(self.SLOT)
        assert self._key(ExplicitSlotStrategy(AsyncMock())) == str(self.SLOT)
        assert self._key(threshold) == str(self.SLOT)

    def test_sequential_fill_does_not_let_users_block_each_other(self):
        """Everyone tapping a time taps the same representative id. Keying the
        lock on it would reject the second booker even though the next channel
        down is free."""
        sequential = SequentialFillStrategy(slot_repo=AsyncMock())

        mine = self._key(sequential)
        theirs = self._key(sequential, user=uuid.uuid4())

        assert mine != theirs
        assert mine != str(self.SLOT)

    def test_sequential_fill_still_stops_the_same_user_double_tapping(self):
        """The one guarantee the slot-id key provided must survive: a
        double-tapped confirm is one booking, not two on two channels."""
        sequential = SequentialFillStrategy(slot_repo=AsyncMock())

        assert self._key(sequential) == self._key(sequential)


# ── admin path is never re-routed by a strategy ───────────────────────────────

@pytest.mark.asyncio
async def test_admin_booking_ignores_the_configured_strategy():
    """Admin booking must claim the slot the admin picked. It proves this by
    passing no strategy at all, so there is nothing to reassign the channel."""
    from app.services.reservation import ReservationService

    svc = ReservationService.__new__(ReservationService)
    svc._user_repo = AsyncMock()
    svc._book = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    user = SimpleNamespace(id=uuid.uuid4(), is_banned=False)
    svc._user_repo.get_by_id = AsyncMock(return_value=user)
    slot_id = uuid.uuid4()

    with patch("app.services.reservation.enqueue_reservation_creation_notification"):
        with patch(
            "app.services.reservation.get_reservation_strategy"
        ) as build_strategy:
            await svc.admin_create_reservation(
                user_id=user.id, slot_id=slot_id, actor="admin"
            )

    build_strategy.assert_not_called()
    _, kwargs = svc._book.await_args
    assert "strategy" not in kwargs
