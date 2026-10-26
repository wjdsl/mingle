"""채팅 요청/응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.conversation import NoteOut, StateOut


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    title: str
    category: str
    score: float


class CTAOut(BaseModel):
    id: str
    trigger_id: str
    label: str
    description: str
    cta_type: str
    url: str
    payload: dict = {}


class TriggerOut(BaseModel):
    id: str
    code: str
    name: str
    description: str
    cta: CTAOut | None = None


class StoryEventOut(BaseModel):
    code: str
    title: str
    description: str
    narrative: str


class EndingOut(BaseModel):
    code: str
    title: str
    description: str


class ChatResponse(BaseModel):
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    reply: str
    provider: str
    latency_ms: int
    state: StateOut
    sources: list[SourceOut] = []
    triggers: list[TriggerOut] = []
    story_events: list[StoryEventOut] = []
    ending: EndingOut | None = None
    notes_updated: list[NoteOut] = []
    guardrail_triggered: bool = False
