import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.db.models.user_broadcast import UserBroadcastAudience

_VALID_AUDIENCES = {a.value for a in UserBroadcastAudience}
_VALID_PARSE_MODES = {"HTML", "Markdown", "plain"}


class AudiencePreviewRequest(BaseModel):
    audience_type: str

    @field_validator("audience_type")
    @classmethod
    def validate_audience(cls, v: str) -> str:
        if v not in _VALID_AUDIENCES:
            raise ValueError(f"audience_type must be one of {sorted(_VALID_AUDIENCES)}")
        return v


class AudiencePreviewResponse(BaseModel):
    count: int


class UserBroadcastCreate(BaseModel):
    audience_type: str
    message: str
    parse_mode: str = "HTML"

    @field_validator("audience_type")
    @classmethod
    def validate_audience(cls, v: str) -> str:
        if v not in _VALID_AUDIENCES:
            raise ValueError(f"audience_type must be one of {sorted(_VALID_AUDIENCES)}")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1:
            raise ValueError("message must not be empty")
        if len(v) > 4096:
            raise ValueError("message must not exceed 4096 characters")
        return v

    @field_validator("parse_mode")
    @classmethod
    def validate_parse_mode(cls, v: str) -> str:
        if v not in _VALID_PARSE_MODES:
            raise ValueError("parse_mode must be HTML, Markdown, or plain")
        return v


class UserBroadcastCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    audience_type: str
    total_recipients: int


class UserBroadcastProgress(BaseModel):
    id: uuid.UUID
    status: str
    audience_type: str
    total_recipients: int
    success_count: int
    failed_count: int
    blocked_count: int
    progress_percent: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class UserBroadcastHistoryItem(BaseModel):
    id: uuid.UUID
    audience_type: str
    status: str
    message: str
    total_recipients: int
    success_count: int
    failed_count: int
    blocked_count: int
    created_at: datetime
    completed_at: Optional[datetime] = None


class PaginatedUserBroadcasts(BaseModel):
    items: list[UserBroadcastHistoryItem]
    total: int
    page: int
    pages: int
