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
    no_show_applied: bool


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


class DaySummary(BaseModel):
    total: int
    active: int
    completed: int
    cancelled: int
    no_show: int


class PaginatedReservations(BaseModel):
    items: list[ReservationItem]
    total: int
    page: int
    pages: int
    summary: DaySummary
