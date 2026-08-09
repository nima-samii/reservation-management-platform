from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SettingChoiceOut(BaseModel):
    """One option of a `select`-widget setting. `value` is what PATCH accepts."""

    value: str
    label: str


class SettingFieldMetaOut(BaseModel):
    key: str
    label: str
    description: str
    type: str
    example: Any
    min: Optional[float] = None
    max: Optional[float] = None
    placeholder: Optional[str] = None
    restart_behavior: str
    runtime_safe: bool
    widget: Optional[str] = None
    choices: Optional[list[SettingChoiceOut]] = None


class SettingCategoryMetaOut(BaseModel):
    key: str
    label: str
    fields: list[SettingFieldMetaOut]


class MembershipChannelItem(BaseModel):
    id: int
    url: str = Field(min_length=1)


class MembershipChannelsBody(BaseModel):
    channels: list[MembershipChannelItem]
