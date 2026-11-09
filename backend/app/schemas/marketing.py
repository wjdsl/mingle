"""마케팅 이벤트(CTA 클릭) 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TrackEventRequest(BaseModel):
    conversation_id: str
    cta_id: str
    event_type: Literal["click"] = "click"
    metadata: dict = Field(default_factory=dict)


class MarketingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    trigger_id: str
    cta_id: str | None = None
    event_type: str
    extra: dict = {}
    created_at: datetime
