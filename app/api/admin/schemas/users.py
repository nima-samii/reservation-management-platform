from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class CountryItem(BaseModel):
    id: uuid.UUID
    name: str
    flag_emoji: Optional[str] = None
    code: str

    model_config = {"from_attributes": True}


class ScoreTransactionItem(BaseModel):
    id: uuid.UUID
    delta: int
    transaction_type: str
    reason: Optional[str] = None
    created_at: datetime


class UserListItem(BaseModel):
    id: uuid.UUID
    telegram_id: int
    public_user_code: str
    full_name: str
    username: Optional[str] = None
    gender: Optional[str] = None
    country: Optional[CountryItem] = None
    participation_score: int
    is_active: bool
    is_banned: bool
    created_at: datetime


class UserDetail(UserListItem):
    recent_transactions: list[ScoreTransactionItem] = []


class UserPatch(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    country_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None
    is_banned: Optional[bool] = None


class ScoreAdjustRequest(BaseModel):
    delta: int
    reason: str

    @field_validator("delta")
    @classmethod
    def delta_nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("delta must not be zero")
        if not -100 <= v <= 100:
            raise ValueError("delta must be between -100 and 100")
        return v

    @field_validator("reason")
    @classmethod
    def reason_min_length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("reason must be at least 5 characters")
        return v


class ScoreAdjustResponse(BaseModel):
    new_score: int
    transaction_id: uuid.UUID


class PaginatedUsers(BaseModel):
    items: list[UserListItem]
    total: int
    page: int
    pages: int


class PaginatedTransactions(BaseModel):
    items: list[ScoreTransactionItem]
    total: int
    page: int
    pages: int


class SendMessageRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        return v


class SendMessageResponse(BaseModel):
    ok: bool
    telegram_message_id: int | None = None
