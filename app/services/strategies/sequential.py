"""SEQUENTIAL_FILL — one logical time per slot, channel chosen at booking time.

The inverse of THRESHOLD_UNLOCK. Instead of opening channels one after another
and letting the user pick a channel's slot, every active channel participates
from the start and the user never sees channels at all: each clock time is
offered once, and the booking lands on the highest-priority channel that still
has that time free.

That moves the channel decision from *display* time to *booking* time, which is
the whole point — the choice is then made against the state at the instant of
booking, under a row lock, instead of against a keyboard the user may have been
staring at for a minute. ``CHANNEL_CAPACITY_THRESHOLD`` has no meaning here:
channels fill strictly in priority order with no ratio to tune.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.config import RESERVATION_STRATEGY_SEQUENTIAL_FILL, settings
from app.core.exceptions import NotFoundError, SlotUnavailableError
from app.db.models.slot import ReservationSlot
from app.repositories.slot import SlotRepository
from app.services.strategies.base import GroupedSlots, SlotRef


class SequentialFillStrategy:
    """Offer each time once; fill channels in priority order.

    Takes no ``ChannelRepository``: channel priority is applied inside the two
    SQL statements this strategy uses, so there is no channel bookkeeping to do
    in Python. ``config`` is accepted for symmetry with the other strategies
    and to keep the seam's dependency on settings visible, even though this
    strategy currently reads no tunables — it has none.
    """

    name = RESERVATION_STRATEGY_SEQUENTIAL_FILL
    # The tapped id names a *time*, not the row to book: resolution re-picks
    # the row by priority. See SlotResolutionStrategy.resolves_by_identity.
    resolves_by_identity = False

    def __init__(
        self,
        *,
        slot_repo: SlotRepository,
        config: Any = settings,
    ) -> None:
        self._repo = slot_repo
        self._config = config

    async def list_bookable_slots(
        self, slot_date: date, *, now: datetime
    ) -> GroupedSlots:
        """Every still-open time on the date, each appearing exactly once.

        All of them go in ``recommended``. ``more_available`` is the
        "additional channels" section of the keyboard, and under this strategy
        there is no such thing: channels are an implementation detail the user
        never chooses between, so a second section would have nothing to hold.
        """
        slots = await self._repo.get_distinct_open_slots_for_date(slot_date, now)
        return GroupedSlots(recommended=slots, more_available=[])

    async def resolve_slot(self, slot_ref: SlotRef) -> ReservationSlot:
        """Book the highest-priority channel still free at the referenced time.

        Both :data:`SlotRef` shapes reduce to a ``slot_datetime``:

        * a ``datetime`` (``lslot:HH:MM``) *is* the answer, and needs no query;
        * a ``uuid`` (``slot:{uuid}``, from a keyboard rendered before this
          strategy shipped, or by an older client) names a representative row
          that is read **only** for its time — deliberately without a lock,
          since holding a row this booking is not going to claim would block a
          booker the database could have served. Its channel and ``is_booked``
          state are irrelevant; the row that gets booked is decided now, by
          priority, against current state.
        """
        if isinstance(slot_ref, datetime):
            slot_datetime = slot_ref
        else:
            tapped = await self._repo.get_by_id(slot_ref)
            if not tapped:
                raise NotFoundError("Slot")
            slot_datetime = tapped.slot_datetime

        slot = await self._repo.lock_next_slot_by_priority(slot_datetime)
        if not slot:
            # Every channel is taken at this time, or being taken right now.
            # Same signal the user already gets from the explicit path, so the
            # handler's "pick another slot" flow needs no new branch.
            raise SlotUnavailableError()
        return slot
