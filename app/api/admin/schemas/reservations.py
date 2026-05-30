from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, computed_field, model_validator


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


class ChannelListItem(BaseModel):
    id: uuid.UUID
    name: str
    telegram_channel_id: int
    capacity: int
    priority: int
    is_active: bool

    model_config = {"from_attributes": True}
