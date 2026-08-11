"""THRESHOLD_UNLOCK — channels open one after another as each one fills up."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from app.core.config import RESERVATION_STRATEGY_THRESHOLD_UNLOCK, settings
from app.db.models.slot import ReservationSlot
from app.repositories.channel import ChannelRepository
from app.repositories.slot import SlotRepository
from app.services.strategies.base import GroupedSlots
from app.services.strategies.explicit import ExplicitSlotStrategy


class ThresholdUnlockStrategy:
    """Channel 1 is always open; channel N+1 unlocks once channel N reaches
    ``CHANNEL_CAPACITY_THRESHOLD`` fill ratio for that day.

    Every open channel contributes its own slots, so the same clock time can
    appear once per channel. Because each button names one physical slot,
    resolution is identity — the user already picked the channel implicitly.

    ``config`` is the settings object the listing tunables are read from. It is
    injected rather than reached for globally so a caller can evaluate the gate
    against a specific configuration, and so the strategy's dependency on
    settings is visible in its signature. It defaults to the live singleton,
    which the admin panel mutates in place — the threshold is therefore read on
    every call and stays hot-reloadable.
    """

    name = RESERVATION_STRATEGY_THRESHOLD_UNLOCK

    def __init__(
        self,
        *,
        slot_repo: SlotRepository,
        channel_repo: ChannelRepository,
        config: Any = settings,
    ) -> None:
        self._repo = slot_repo
        self._channel_repo = channel_repo
        self._config = config
        self._resolution = ExplicitSlotStrategy(slot_repo)

    async def list_bookable_slots(
        self, slot_date: date, *, now: datetime
    ) -> GroupedSlots:
        """
        Returns slots grouped into two sections:
        - recommended: Channel 1 (always open) available slots
        - more_available: Channel 2+ slots, unlocked when the preceding channel
          reaches CHANNEL_CAPACITY_THRESHOLD fill ratio for that day
        """
        threshold = self._config.CHANNEL_CAPACITY_THRESHOLD
        channels = await self._channel_repo.get_active_channels_ordered()

        recommended: list[ReservationSlot] = []
        more_available: list[ReservationSlot] = []
        next_channel_unlocked = False

        for i, channel in enumerate(channels):
            if i > 0 and not next_channel_unlocked:
                break

            slots = await self._repo.get_available_slots_for_date_and_channel(
                slot_date, channel.id, now
            )
            booked = await self._channel_repo.get_reservation_count_for_date(
                channel.id, slot_date
            )
            # Real per-day capacity is the number of slots actually generated for
            # this channel on this date — NOT the settings-derived _slots_per_day().
            # The latter recomputes from the current SLOT_* settings, so tightening
            # the schedule after slots were generated shrinks the denominator and
            # unlocks the next channel far too early. (Same bug class as the
            # dashboard "/ 100" capacity fix.) A channel with no slots that day
            # (capacity 0) is treated as "full" so the next channel still unlocks
            # and the user is never left with an empty list.
            capacity = await self._repo.count_slots_for_date_and_channel(
                slot_date, channel.id
            )
            fill_ratio = booked / capacity if capacity > 0 else 1.0
            next_channel_unlocked = fill_ratio >= threshold

            if i == 0:
                recommended.extend(slots)
            else:
                more_available.extend(slots)

        return GroupedSlots(recommended=recommended, more_available=more_available)

    async def resolve_slot(self, slot_id: uuid.UUID) -> ReservationSlot:
        # One button per physical slot ⇒ the id the user tapped is the slot to
        # book. Delegated rather than reimplemented so both this strategy and
        # the admin path share a single by-id resolution implementation.
        return await self._resolution.resolve_slot(slot_id)
