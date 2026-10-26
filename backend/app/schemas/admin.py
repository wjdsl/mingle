"""관리자 로그인 / B2B Dashboard 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=4, max_length=200)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    admin: AdminOut


class Totals(BaseModel):
    sessions: int
    conversations: int
    completed_conversations: int
    messages: int
    avg_latency_ms: float
    trigger_impressions: int
    trigger_clicks: int
    ctr: float


class PersonaStats(BaseModel):
    persona_id: str
    slug: str
    name: str
    conversations: int
    completed: int
    messages: int
    avg_turns: float
    avg_affinity: float
    trigger_impressions: int
    trigger_clicks: int


class TriggerStats(BaseModel):
    trigger_id: str
    code: str
    name: str
    persona_name: str
    impressions: int
    clicks: int
    ctr: float


class DailyPoint(BaseModel):
    date: str
    sessions: int
    conversations: int
    messages: int


class RecentConversation(BaseModel):
    conversation_id: str
    persona_name: str
    session_hint: str
    stage: str
    affinity: int
    turn_count: int
    status: str
    last_message_at: datetime | None = None


class DashboardOverview(BaseModel):
    generated_at: datetime
    range_days: int
    totals: Totals
    personas: list[PersonaStats]
    triggers: list[TriggerStats]
    daily: list[DailyPoint]
    stages: dict[str, int]
    recent_conversations: list[RecentConversation]
