from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.db.models.reservation import AttendanceStatus

# Imported rather than restated so the HTTP contract and the service can never
# disagree about what an admin may enter. The service re-checks both — it is the
# authority, and it is reachable from places that are not this API.
from app.services.reservation import ATTENDANCE_REASON_MAX, ATTENDANCE_SCORE_LIMIT


class CancelReservationBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=256)


class RecordAttendanceBody(BaseModel):
    """An admin's attendance decision for one completed reservation.

    The outcome and the score are independent fields on purpose: attended for
    +10, attended for 0, attended for -5 and absent for +2 are all valid bodies.
    Nothing here derives one from the other, and the reason is what explains the
    combination to the user — so it is required, not optional like the
    cancellation reason above.
    """

    attendance_status: AttendanceStatus
    score_delta: int = Field(
        ..., ge=-ATTENDANCE_SCORE_LIMIT, le=ATTENDANCE_SCORE_LIMIT
    )
    reason: str = Field(..., min_length=1, max_length=ATTENDANCE_REASON_MAX)

    @field_validator("reason")
    @classmethod
    def _reason_is_not_blank(cls, value: str) -> str:
        # min_length runs on the raw string, so "   " passes it. The user is
        # shown this text, so whitespace is not an explanation.
        stripped = value.strip()
        if not stripped:
            raise ValueError("An explanation is required.")
        return stripped


class CreateReservationBody(BaseModel):
    user_id: uuid.UUID
    slot_id: uuid.UUID


class SlotInfo(BaseModel):
    id: uuid.UUID
    slot_datetime: datetime
    slot_time_local: str  # HH:MM in configured TIMEZONE


class ChannelInfo(BaseModel):
    id: uuid.UUID
    name: str


class CountryInfo(BaseModel):
    name: str
    flag_emoji: Optional[str] = None


class UserInfo(BaseModel):
    id: uuid.UUID
    public_user_code: str
    full_name: str
    gender: Optional[str] = None
    country: Optional[CountryInfo] = None
    participation_score: int


class ReservationItem(BaseModel):
    id: uuid.UUID
    status: str
    notes: Optional[str] = None
    slot: SlotInfo
    channel: ChannelInfo
    user: UserInfo

    # True only for the retired no-show penalty, never for an attendance
    # decision. The two are told apart deliberately: this one always meant -1
    # and cannot be re-decided, so the panel has to render it as history rather
    # than as an outcome an admin chose.
    no_show_applied: bool

    # ── The attendance decision, null until an admin records one ───────────
    # Flat fields rather than a nested object: all five are written together
    # and read together, the CSV export needs them as columns anyway, and
    # "no decision yet" is then five nulls instead of an absent object every
    # caller has to guard.
    attendance_status: Optional[str] = None
    attendance_score_delta: Optional[int] = None
    attendance_reason: Optional[str] = None
    attendance_marked_by: Optional[str] = None
    attendance_marked_at: Optional[datetime] = None


class ReservationDetail(ReservationItem):
    pass


class NoShowResponse(BaseModel):
    reservation_id: uuid.UUID
    user_id: uuid.UUID
    new_score: int
    transaction_id: uuid.UUID


class AttendanceResponse(BaseModel):
    """What was recorded, echoed back so the panel need not re-fetch.

    Echoes the decision rather than the reservation because the decision is
    immutable — this is the only response that will ever describe it.
    """

    reservation_id: uuid.UUID
    user_id: uuid.UUID
    attendance_status: str
    score_delta: int
    reason: str
    new_score: int
    transaction_id: uuid.UUID
    # Included so a caller can render the recorded row without re-fetching or
    # inventing a local timestamp — these are the values that were written, not
    # an approximation of them.
    marked_by: str
    marked_at: datetime


class DaySummary(BaseModel):
    """Counts for the filter bar, over the current date/channel/search window.

    ``no_show`` keeps its name but has widened to "recorded as absent by either
    system" — the legacy penalty flag or an `absent` attendance decision.
    Renaming it would have broken every existing caller; leaving it reading
    only the legacy flag would have frozen it at zero the moment automatic
    scoring was removed.
    """

    total: int
    active: int
    completed: int
    cancelled: int
    no_show: int
    attended: int = 0
    # Completed, no decision recorded, not already scored by the legacy
    # penalty — the number of sessions still waiting on an admin.
    awaiting_decision: int = 0


class PaginatedReservations(BaseModel):
    items: list[ReservationItem]
    total: int
    page: int
    pages: int
    summary: DaySummary
