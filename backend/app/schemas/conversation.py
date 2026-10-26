"""대화 / 상태 / 기억(User Note) 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    persona_slug: str
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class StateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    turn_count: int
    affinity: int
    trust: int
    stage: str
    chapter: int
    flags: dict = {}
    ending_code: str | None = None
    updated_at: datetime | None = None


class ConversationSummary(BaseModel):
    id: str
    persona_id: str
    persona_slug: str
    persona_name: str
    avatar_emoji: str
    theme_color: str
    title: str
    status: str
    turn_count: int = 0
    affinity: int = 0
    stage: str = "낯섦"
    ending_code: str | None = None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None


class ConversationDetail(ConversationSummary):
    persona_tagline: str = ""
    chapter: int = 1
    trust: int = 0
    ending_title: str | None = None
    message_count: int = 0


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    provider: str | None = None
    latency_ms: int | None = None
    extra: dict = {}
    created_at: datetime


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    value: str
    category: str
    importance: float
    confidence: float
    source: str
    updated_at: datetime


class NoteCreate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1000)
    category: str = Field(default="profile", pattern="^(profile|preference|event|relationship)$")
    importance: float = Field(default=0.6, ge=0.0, le=1.0)
    persona_id: str | None = None


class NoteUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=1000)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
