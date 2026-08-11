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
from app.services.strategies.threshold import ThresholdUnlockStrategy


def _slot() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), channel_id=uuid.uuid4())


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

    def test_sequential_fill_fails_fast_instead_of_degrading(self):
        # It must never fall back to THRESHOLD_UNLOCK: a half-wired strategy
        # silently booking through the other one is the failure mode this guards.
        with pytest.raises(UnsupportedReservationStrategyError) as exc:
            self._build(name=RESERVATION_STRATEGY_SEQUENTIAL_FILL)
        assert exc.value.strategy == RESERVATION_STRATEGY_SEQUENTIAL_FILL

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
