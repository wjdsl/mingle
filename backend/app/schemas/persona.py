"""페르소나 응답 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PersonaSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    tagline: str
    category: str
    description: str
    avatar_emoji: str
    theme_color: str
    tags: list[str] = []
    starter_questions: list[str] = []
    sort_order: int = 0


class PersonaDetail(PersonaSummary):
    worldview: str
    greeting: str
    speech_style: str
    guardrails: str
    knowledge_count: int = 0
    conversation_count: int = 0
    created_at: datetime


class KnowledgeDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    category: str
