"""Resolution policy for callers that already know the physical slot."""
from __future__ import annotations

import uuid

from sqlalchemy.exc import OperationalError

from app.core.exceptions import NotFoundError, SlotUnavailableError
from app.db.models.slot import ReservationSlot
from app.repositories.slot import SlotRepository
from app.services.strategies.base import SlotRef


class ExplicitSlotStrategy:
    """Book exactly the slot that was named — never substitute another channel.

    This is **not** selectable through ``settings.RESERVATION_STRATEGY``. It is
    the fixed resolution policy for callers that have already chosen the
    physical slot and must keep that choice whatever strategy is configured:

    * the admin panel, where an admin picks the channel deliberately
    * ``slot:{uuid}`` callbacks, which name exactly one physical slot

    It is also the resolution half of THRESHOLD_UNLOCK, which renders one
    button per physical slot and therefore resolves by identity.
    """

    name = "EXPLICIT"
    resolves_by_identity = True

    def __init__(self, slot_repo: SlotRepository) -> None:
        self._slot_repo = slot_repo

    async def resolve_slot(self, slot_ref: SlotRef) -> ReservationSlot:
        if not isinstance(slot_ref, uuid.UUID):
            # A logical "any channel at this time" reference, which identity
            # resolution has no way to honour. This is reachable in production:
            # a user is offered lslot: buttons under SEQUENTIAL_FILL, an admin
            # switches the strategy, and the user then taps Confirm. Their
            # keyboard is stale, which is exactly what SlotUnavailableError
            # means to the handler — it already offers "pick another slot".
            raise SlotUnavailableError()

        try:
            slot = await self._slot_repo.get_slot_with_lock(slot_ref)
        except OperationalError:
            # FOR UPDATE NOWAIT lost the race to a concurrent booking.
            raise SlotUnavailableError()

        if not slot:
            raise NotFoundError("Slot")
        return slot
