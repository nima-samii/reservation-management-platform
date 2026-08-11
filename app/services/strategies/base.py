"""The two seams a reservation strategy is allowed to control.

A strategy decides only:

1. **listing**    — which slots a user is offered for a date
2. **resolution** — which physical ``(slot, channel)`` row a booking claims

Everything else is shared reservation logic and deliberately stays in the
services: past-slot and same-day-cutoff rules, the daily limit, the max-active
limit, ``is_booked``, score, notifications and cancellation. A new strategy
must never be able to fork any of it.

The two seams are separate protocols on purpose. ``ReservationService`` needs
only resolution, ``SlotService`` needs only listing, and a resolution-only
policy (see ``ExplicitSlotStrategy``) is a legitimate implementation that has
no listing behaviour at all.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Protocol, TypedDict

from app.db.models.slot import ReservationSlot


class GroupedSlots(TypedDict):
    """Slots split into the two sections the slot keyboard renders."""

    recommended: list[ReservationSlot]
    more_available: list[ReservationSlot]


class SlotListingStrategy(Protocol):
    """Seam 1 — what the user is offered for a given date.

    ``now`` is passed in rather than read from the clock so the caller's
    shared pre-checks (same-day cutoff) and the strategy's own filtering
    always agree on a single instant.
    """

    async def list_bookable_slots(
        self, slot_date: date, *, now: datetime
    ) -> GroupedSlots: ...


class SlotResolutionStrategy(Protocol):
    """Seam 2 — which physical slot row a booking claims and row-locks.

    Implementations return a slot locked ``FOR UPDATE``, or raise:
    ``SlotUnavailableError`` when the row is held by a competing booking, and
    ``NotFoundError`` when no such slot exists.
    """

    #: True when ``resolve_slot`` claims exactly the row named by ``slot_id``.
    #:
    #: This is not cosmetic — it decides what the booking contends for, and so
    #: what the advisory lock in ``ReservationService._book`` may be keyed on.
    #: Under identity resolution two users tapping the same button want the
    #: same row, so the slot id is the contended resource. Under a strategy
    #: that re-picks the row (SEQUENTIAL_FILL), everyone tapping a given time
    #: taps the *same representative id* while intending different rows, so
    #: locking that id would reject bookings the database could satisfy.
    resolves_by_identity: bool

    async def resolve_slot(self, slot_id: uuid.UUID) -> ReservationSlot: ...


class ReservationStrategy(SlotListingStrategy, SlotResolutionStrategy, Protocol):
    """A full strategy, selectable through ``settings.RESERVATION_STRATEGY``."""

    name: str
