import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from app.db.models.user_broadcast import (
    MediaType,
    RecurrenceFrequency,
    UserBroadcastAudience,
)
from app.services.segmentation import SegmentFilter

_VALID_AUDIENCES = {a.value for a in UserBroadcastAudience}
_VALID_PARSE_MODES = {"HTML", "Markdown", "plain"}
_VALID_MEDIA = {m.value for m in MediaType}
_VALID_FREQUENCIES = {f.value for f in RecurrenceFrequency}


class RecurrenceSpec(BaseModel):
    frequency: str
    interval: int = 1
    day_of_week: Optional[int] = None  # 0=Mon .. 6=Sun
    day_of_month: Optional[int] = None  # 1..31
    time_of_day: Optional[str] = None  # "HH:MM" local time; defaults to creation time

    @field_validator("frequency")
    @classmethod
    def _freq(cls, v: str) -> str:
        if v not in _VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of {sorted(_VALID_FREQUENCIES)}")
        return v

    @field_validator("time_of_day")
    @classmethod
    def _tod(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("time_of_day must be 'HH:MM'")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("time_of_day must be a valid 24h time 'HH:MM'")
        return f"{hh:02d}:{mm:02d}"

    @field_validator("interval")
    @classmethod
    def _interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval must be >= 1")
        return v

    @field_validator("day_of_week")
    @classmethod
    def _dow(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 6):
            raise ValueError("day_of_week must be 0..6")
        return v

    @field_validator("day_of_month")
    @classmethod
    def _dom(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 31):
            raise ValueError("day_of_month must be 1..31")
        return v


def _validate_audience(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in _VALID_AUDIENCES:
        raise ValueError(f"audience_type must be one of {sorted(_VALID_AUDIENCES)}")
    return v


class AudiencePreviewRequest(BaseModel):
    """Either a Sprint-1 quick segment (audience_type) or a Sprint-2 advanced
    segment (filters). Backward compatible: audience_type alone still works."""

    audience_type: Optional[str] = None
    filters: Optional[SegmentFilter] = None

    @model_validator(mode="after")
    def _check(self) -> "AudiencePreviewRequest":
        if self.filters is None and self.audience_type is None:
            raise ValueError("provide either audience_type or filters")
        _validate_audience(self.audience_type)
        return self


class AudiencePreviewResponse(BaseModel):
    count: int
    with_username: int
    without_username: int
    avg_score: float


def _check_parse_mode(v: str) -> str:
    if v not in _VALID_PARSE_MODES:
        raise ValueError("parse_mode must be HTML, Markdown, or plain")
    return v


def _check_media(media_type: str) -> str:
    if media_type not in _VALID_MEDIA:
        raise ValueError(f"media_type must be one of {sorted(_VALID_MEDIA)}")
    return media_type


class UserBroadcastCreate(BaseModel):
    audience_type: Optional[str] = None
    filters: Optional[SegmentFilter] = None
    message: Optional[str] = None
    parse_mode: str = "HTML"

    # Sprint 3
    media_type: str = MediaType.TEXT.value
    media_file_id: Optional[str] = None
    template_id: Optional[uuid.UUID] = None
    scheduled_for: Optional[datetime] = None
    save_as_draft: bool = False
    recurrence: Optional[RecurrenceSpec] = None

    @model_validator(mode="after")
    def _check(self) -> "UserBroadcastCreate":
        if self.filters is None and self.audience_type is None:
            raise ValueError("provide either audience_type or filters")
        _validate_audience(self.audience_type)
        _check_parse_mode(self.parse_mode)
        _check_media(self.media_type)
        # message may be omitted only when prefilled from a template
        if self.message is not None:
            self.message = self.message.strip()
            if len(self.message) > 4096:
                raise ValueError("message must not exceed 4096 characters")
        if not self.message and self.template_id is None:
            raise ValueError("message is required unless template_id is provided")
        # photo/document need a file_id (unless inherited from a template)
        if self.media_type != MediaType.TEXT.value and not self.media_file_id and self.template_id is None:
            raise ValueError("media_file_id is required for photo/document")
        return self


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
    media_type: str = MediaType.TEXT.value
    total_recipients: int
    success_count: int
    failed_count: int
    blocked_count: int
    scheduled_for: Optional[datetime] = None
    template_id: Optional[uuid.UUID] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class PaginatedUserBroadcasts(BaseModel):
    items: list[UserBroadcastHistoryItem]
    total: int
    page: int
    pages: int


# ── Drafts ──────────────────────────────────────────────────────────────────

class DraftUpdate(BaseModel):
    """Patch a draft. All fields optional; only provided ones are applied."""

    message: Optional[str] = None
    parse_mode: Optional[str] = None
    audience_type: Optional[str] = None
    filters: Optional[SegmentFilter] = None
    media_type: Optional[str] = None
    media_file_id: Optional[str] = None
    scheduled_for: Optional[datetime] = None

    @model_validator(mode="after")
    def _check(self) -> "DraftUpdate":
        if self.parse_mode is not None:
            _check_parse_mode(self.parse_mode)
        if self.media_type is not None:
            _check_media(self.media_type)
        if self.audience_type is not None:
            _validate_audience(self.audience_type)
        if self.message is not None:
            self.message = self.message.strip()
            if len(self.message) > 4096:
                raise ValueError("message must not exceed 4096 characters")
        return self


# ── Templates ─────────────────────────────────────────────────────────────--

class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    message: str
    parse_mode: str = "HTML"
    media_type: str = MediaType.TEXT.value
    media_file_id: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "TemplateCreate":
        _check_parse_mode(self.parse_mode)
        _check_media(self.media_type)
        self.name = self.name.strip()
        self.message = self.message.strip()
        if not self.name:
            raise ValueError("name is required")
        if not self.message:
            raise ValueError("message is required")
        if len(self.message) > 4096:
            raise ValueError("message must not exceed 4096 characters")
        if self.media_type != MediaType.TEXT.value and not self.media_file_id:
            raise ValueError("media_file_id is required for photo/document")
        return self


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    message: Optional[str] = None
    parse_mode: Optional[str] = None
    media_type: Optional[str] = None
    media_file_id: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "TemplateUpdate":
        if self.parse_mode is not None:
            _check_parse_mode(self.parse_mode)
        if self.media_type is not None:
            _check_media(self.media_type)
        return self


class TemplateItem(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    message: str
    parse_mode: str
    media_type: str
    media_file_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ── Media upload ─────────────────────────────────────────────────────────────

class MediaUploadResponse(BaseModel):
    media_type: str
    media_file_id: str
