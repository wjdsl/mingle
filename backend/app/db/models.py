"""SQLAlchemy ORM 모델.

PostgreSQL에서는 pgvector 타입을, SQLite(개발용)에서는 JSON 컬럼을 사용한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base

if settings.is_postgres:
    from pgvector.sqlalchemy import Vector

    EmbeddingType: Any = Vector(settings.embedding_dim)
else:
    EmbeddingType = JSON


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# 페르소나 / RAG 지식
# --------------------------------------------------------------------------- #
class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    tagline: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(40), default="자체 제작")  # IP | 자체 제작 | 브랜드
    description: Mapped[str] = mapped_column(Text, default="")
    worldview: Mapped[str] = mapped_column(Text, default="")
    character_sheet: Mapped[str] = mapped_column(Text, default="")
    speech_style: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    guardrails: Mapped[str] = mapped_column(Text, default="")
    greeting: Mapped[str] = mapped_column(Text, default="")
    avatar_emoji: Mapped[str] = mapped_column(String(8), default="✨")
    theme_color: Mapped[str] = mapped_column(String(16), default="#7C6CF0")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    starter_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PersonaKnowledge(Base):
    """RAG 검색 대상 문서 청크."""

    __tablename__ = "persona_knowledge"
    __table_args__ = (Index("ix_knowledge_persona_category", "persona_id", "category"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("personas.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="world")  # world | character | product | faq
    embedding: Mapped[Any] = mapped_column(EmbeddingType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# 사용자 세션 (비회원 + 개인 코드)
# --------------------------------------------------------------------------- #
class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_hint: Mapped[str] = mapped_column(String(8), default="")
    display_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_session_persona", "session_id", "persona_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True
    )
    persona_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("personas.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | completed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RelationshipState(Base):
    """상태 기반 관계/스토리 진행."""

    __tablename__ = "relationship_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    affinity: Mapped[int] = mapped_column(Integer, default=10)  # 0~100
    trust: Mapped[int] = mapped_column(Integer, default=0)  # 0~100
    stage: Mapped[str] = mapped_column(String(30), default="낯섦")
    chapter: Mapped[int] = mapped_column(Integer, default=1)
    flags: Mapped[dict] = mapped_column(JSON, default=dict)
    ending_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserNote(Base):
    """LLM/규칙으로 추출한 장기 기억."""

    __tablename__ = "user_notes"
    __table_args__ = (
        UniqueConstraint("session_id", "persona_id", "key", name="uq_note_session_persona_key"),
        Index("ix_notes_session_persona", "session_id", "persona_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True
    )
    persona_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("personas.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="profile")  # profile | preference | event | relationship
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    source: Mapped[str] = mapped_column(String(30), default="rule")  # rule | llm | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------- #
# 스토리 / 엔딩
# --------------------------------------------------------------------------- #
class StoryEventDef(Base):
    __tablename__ = "story_events"
    __table_args__ = (UniqueConstraint("persona_id", "code", name="uq_story_persona_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("personas.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    narrative_hint: Mapped[str] = mapped_column(Text, default="")
    chapter: Mapped[int] = mapped_column(Integer, default=1)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    effects: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class EndingDef(Base):
    __tablename__ = "endings"
    __table_args__ = (UniqueConstraint("persona_id", "code", name="uq_ending_persona_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("personas.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ConversationEventLog(Base):
    __tablename__ = "conversation_events"
    __table_args__ = (Index("ix_conversation_events_conv_kind", "conversation_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # story | ending
    code: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# 마케팅 Trigger / CTA
# --------------------------------------------------------------------------- #
class MarketingTriggerDef(Base):
    __tablename__ = "marketing_triggers"
    __table_args__ = (UniqueConstraint("persona_id", "code", name="uq_trigger_persona_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("personas.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    use_llm_judge: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_turns: Mapped[int] = mapped_column(Integer, default=3)
    max_fires: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CTADef(Base):
    __tablename__ = "ctas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trigger_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("marketing_triggers.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    cta_type: Mapped[str] = mapped_column(String(30), default="link")  # coupon | purchase | booking | event | link
    url: Mapped[str] = mapped_column(String(500), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketingEvent(Base):
    __tablename__ = "marketing_events"
    __table_args__ = (
        Index("ix_marketing_events_conv_type", "conversation_id", "event_type"),
        Index("ix_marketing_events_trigger_type", "trigger_id", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    trigger_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("marketing_triggers.id", ondelete="CASCADE"), index=True
    )
    cta_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ctas.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(20))  # impression | click
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# 공유 / 관리자
# --------------------------------------------------------------------------- #
class ShareCard(Base):
    __tablename__ = "share_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="관리자")
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
