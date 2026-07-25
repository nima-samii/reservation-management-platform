from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def validate_telegram_channel_id(value: int) -> int:
    if value >= 0:
        raise ValueError("telegram_channel_id must be a negative integer (Telegram channel/supergroup ID)")
    return value


def validate_invite_link(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    if not value.startswith("https://t.me/"):
        raise ValueError("invite_link must start with https://t.me/")
    return value


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    telegram_channel_id: int
    invite_link: Optional[str] = None
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateChannelBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    telegram_channel_id: int
    invite_link: Optional[str] = None

    _validate_telegram_channel_id = field_validator("telegram_channel_id")(
        validate_telegram_channel_id
    )
    _validate_invite_link = field_validator("invite_link")(validate_invite_link)


class UpdateChannelBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    invite_link: Optional[str] = None
    is_active: Optional[bool] = None

    _validate_invite_link = field_validator("invite_link")(validate_invite_link)


class MoveChannelBody(BaseModel):
    direction: Literal["up", "down"]
