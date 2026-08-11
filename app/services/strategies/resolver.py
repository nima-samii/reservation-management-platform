"""Builds the reservation strategy named by ``settings.RESERVATION_STRATEGY``.

This is the only place allowed to read that setting, so adding a strategy means
adding a branch here rather than an ``if`` somewhere in the services.
"""
from __future__ import annotations

from typing import Any

from app.core.config import (
    RESERVATION_STRATEGIES,
    RESERVATION_STRATEGY_SEQUENTIAL_FILL,
    RESERVATION_STRATEGY_THRESHOLD_UNLOCK,
)
from app.core.config import settings as global_settings
from app.core.exceptions import UnsupportedReservationStrategyError
from app.repositories.channel import ChannelRepository
from app.repositories.slot import SlotRepository
from app.services.strategies.base import ReservationStrategy
from app.services.strategies.sequential import SequentialFillStrategy
from app.services.strategies.threshold import ThresholdUnlockStrategy


def get_reservation_strategy(
    *,
    slot_repo: SlotRepository,
    channel_repo: ChannelRepository,
    config: Any = None,
    name: str | None = None,
) -> ReservationStrategy:
    """Build the strategy for the user-facing reservation flow.

    Repositories are passed in rather than built from a session so the strategy
    shares the caller's identity map and unit of work.

    *Which* strategy runs is a deployment-wide switch and is always read from
    the real settings singleton; ``config`` carries only the per-strategy
    tunables, and defaults to that same singleton.

    Raises ``UnsupportedReservationStrategyError`` for a configured-but-not-yet
    -implemented strategy. That is deliberate: a half-wired strategy must fail
    loudly at the entry point rather than silently degrade into a different
    booking behaviour.
    """
    strategy_name = name if name is not None else global_settings.RESERVATION_STRATEGY

    if strategy_name == RESERVATION_STRATEGY_THRESHOLD_UNLOCK:
        return ThresholdUnlockStrategy(
            slot_repo=slot_repo,
            channel_repo=channel_repo,
            config=config if config is not None else global_settings,
        )

    if strategy_name == RESERVATION_STRATEGY_SEQUENTIAL_FILL:
        # No channel_repo: this strategy applies channel priority in SQL and
        # keeps no per-channel state of its own.
        return SequentialFillStrategy(
            slot_repo=slot_repo,
            config=config if config is not None else global_settings,
        )

    # Last line of defence. Configuration already refuses to store a strategy
    # that has no branch above, so reaching here means something bypassed it
    # (a hand-edited override, a direct object.__setattr__). Never fall back.
    if strategy_name in RESERVATION_STRATEGIES:
        raise UnsupportedReservationStrategyError(
            strategy_name,
            "known but not implemented yet",
        )

    raise UnsupportedReservationStrategyError(str(strategy_name), "unknown strategy")
