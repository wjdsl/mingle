"""채팅 오케스트레이션.

한 턴의 처리 순서:
1. 페르소나/상태/기억/최근 대화 로드
2. RAG 검색
3. 관계 상태 갱신 + 스토리 이벤트/엔딩 판정 (연출 지침 확보)
4. 시스템 프롬프트 구성 → LLM 호출(또는 스트리밍)
5. 가드레일 검사
6. 메시지 저장
7. User Note 추출·저장
8. Marketing Trigger / CTA 판정
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Conversation,
    EndingDef,
    Message,
    Persona,
    RelationshipState,
    StoryEventDef,
    UserNote,
    utcnow,
)
from app.services.llm import LLMError, get_llm
from app.services.marketing import TriggerHit, evaluate_triggers
from app.services.memory import load_notes, update_notes
from app.services.persona_prompt import build_system_prompt
from app.services.rag import RetrievedChunk, retrieve
from app.services.story import StoryAdvance, advance_state, get_or_create_state

logger = logging.getLogger(__name__)

TokenEmitter = Callable[[str], Awaitable[None]]

_BLOCKED_PATTERNS = (
    "자살",
    "죽고 싶",
    "죽어버리",
    "폭탄 제조",
    "폭발물 제조",
    "마약 구",
    "마약 사",
    "성착취",
    "아동 착취",
)


class ConversationCompletedError(RuntimeError):
    """이미 엔딩에 도달한 대화."""


class PersonaNotFoundError(RuntimeError):
    pass


@dataclass(slots=True)
class ChatOutcome:
    conversation: Conversation
    persona: Persona
    state: RelationshipState
    user_message: Message
    assistant_message: Message
    reply: str
    provider: str
    latency_ms: int
    sources: list[RetrievedChunk] = field(default_factory=list)
    trigger_hits: list[TriggerHit] = field(default_factory=list)
    story_events: list[StoryEventDef] = field(default_factory=list)
    ending: EndingDef | None = None
    notes_updated: list[UserNote] = field(default_factory=list)
    guardrail_triggered: bool = False


async def create_conversation(
    db: AsyncSession,
    *,
    session_id: str,
    persona: Persona,
    title: str | None = None,
) -> tuple[Conversation, RelationshipState]:
    conversation = Conversation(
        session_id=session_id,
        persona_id=persona.id,
        title=(title or f"{persona.name}와의 대화")[:200],
    )
    db.add(conversation)
    await db.flush()

    state = await get_or_create_state(db, conversation.id)

    greeting = persona.greeting or f"안녕, 나는 {persona.name}이야."
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=greeting,
            provider="system",
            extra={"kind": "greeting"},
        )
    )
    conversation.last_message_at = utcnow()
    await db.flush()
    return conversation, state


async def load_persona(db: AsyncSession, persona_id: str) -> Persona:
    persona = await db.get(Persona, persona_id)
    if persona is None or not persona.is_active:
        raise PersonaNotFoundError("페르소나를 찾을 수 없습니다.")
    return persona


async def _load_history(
    db: AsyncSession, conversation_id: str, limit: int
) -> list[Message]:
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


def _build_rag_query(user_text: str, history: list[Message]) -> str:
    recent_user = [m.content for m in history if m.role == "user"][-2:]
    query = " ".join([*recent_user, user_text]).strip()
    return query[:500]


def _guardrail_reply(persona: Persona) -> str:
    if "존댓말" in (persona.speech_style or ""):
        return (
            "그 이야기는 제가 함부로 다루기 어려운 주제예요. "
            "대신 오늘 하루는 어떠셨는지 들려주시겠어요?"
        )
    return (
        "…그 이야기는 조심스러워서, 다른 이야기를 나누고 싶어. "
        "오늘 하루는 어땠어?"
    )


def apply_guardrail(reply: str, persona: Persona) -> tuple[str, bool]:
    if not settings.guardrail_enabled:
        return reply, False
    lowered = reply.lower()
    if any(pattern in lowered for pattern in _BLOCKED_PATTERNS):
        logger.warning("가드레일 작동: persona=%s", persona.slug)
        return _guardrail_reply(persona), True
    return reply, False


async def process_message(
    db: AsyncSession,
    conversation: Conversation,
    user_text: str,
    *,
    emit: TokenEmitter | None = None,
) -> ChatOutcome:
    if conversation.status == "completed":
        raise ConversationCompletedError("이미 엔딩에 도달한 대화입니다.")

    persona = await load_persona(db, conversation.persona_id)
    state = await get_or_create_state(db, conversation.id)
    notes = await load_notes(db, conversation.session_id, persona.id)
    history = await _load_history(db, conversation.id, settings.context_message_limit)

    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=user_text,
    )
    db.add(user_message)
    await db.flush()

    # 관계 상태 갱신 + 스토리 이벤트 판정 (이번 턴 연출에 반영)
    advance: StoryAdvance = await advance_state(
        db, conversation, state, text=user_text, notes=notes
    )
    hints = list(advance.hints)
    if advance.ending is not None:
        hints.append(
            f"이번 대화는 '{advance.ending.title}' 엔딩으로 마무리된다. "
            f"설정: {advance.ending.description}"
        )

    chunks = await retrieve(
        db, persona.id, _build_rag_query(user_text, history), top_k=settings.rag_top_k
    )
    system_prompt = build_system_prompt(
        persona,
        state,
        notes,
        chunks,
        story_hints=hints,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages += [
        {"role": message.role, "content": message.content}
        for message in history
        if message.role in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": user_text})

    llm = get_llm()
    started = time.perf_counter()
    if emit is None:
        result = await llm.generate(
            messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        reply = result.text
        provider = result.provider
    else:
        parts: list[str] = []
        async for token in llm.stream(
            messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        ):
            parts.append(token)
            await emit(token)
        reply = "".join(parts)
        provider = llm.name
    latency_ms = int((time.perf_counter() - started) * 1000)

    reply = (reply or "").strip()
    if not reply:
        reply = "…잠시 말을 잇지 못했어. 다시 한 번 이야기해줄래?"
    reply, guardrail_triggered = apply_guardrail(reply, persona)

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=reply,
        provider=provider,
        latency_ms=latency_ms,
        extra={
            "sources": [chunk.as_dict() for chunk in chunks],
            "story_events": [event.code for event in advance.events],
            "guardrail": guardrail_triggered,
        },
    )
    db.add(assistant_message)

    conversation.last_message_at = utcnow()
    if conversation.title in ("", f"{persona.name}와의 대화"):
        conversation.title = " ".join(user_text.split())[:40] or conversation.title

    await db.flush()

    notes_updated = await update_notes(
        db, conversation.session_id, persona.id, user_text
    )
    disclosed = any(
        note.category in ("profile", "preference") for note in notes_updated
    )
    if disclosed:
        state.trust = min(100, state.trust + 1)

    trigger_hits = await evaluate_triggers(
        db, conversation, state, user_text, notes
    )

    return ChatOutcome(
        conversation=conversation,
        persona=persona,
        state=state,
        user_message=user_message,
        assistant_message=assistant_message,
        reply=reply,
        provider=provider,
        latency_ms=latency_ms,
        sources=chunks,
        trigger_hits=trigger_hits,
        story_events=advance.events,
        ending=advance.ending,
        notes_updated=notes_updated,
        guardrail_triggered=guardrail_triggered,
    )
