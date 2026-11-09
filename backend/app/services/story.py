"""상태 기반 관계·스토리 분기 / 멀티엔딩."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    ConversationEventLog,
    EndingDef,
    RelationshipState,
    StoryEventDef,
    UserNote,
)
from app.services.conditions import ConditionContext, evaluate

logger = logging.getLogger(__name__)

STAGE_THRESHOLDS: list[tuple[int, str]] = [
    (70, "각별"),
    (40, "친밀"),
    (15, "호기심"),
    (0, "낯섦"),
]

POSITIVE_CUES = (
    "좋아",
    "고마",
    "사랑",
    "최고",
    "행복",
    "즐거",
    "설레",
    "다행",
    "예뻐",
    "멋져",
    "반가",
)
NEGATIVE_CUES = (
    "싫어",
    "짜증",
    "화나",
    "최악",
    "슬퍼",
    "무서",
    "불안",
    "별로",
    "실망",
    "미안",
)


@dataclass(slots=True)
class StoryAdvance:
    events: list[StoryEventDef] = field(default_factory=list)
    ending: EndingDef | None = None
    hints: list[str] = field(default_factory=list)


def stage_for(affinity: int) -> str:
    for threshold, name in STAGE_THRESHOLDS:
        if affinity >= threshold:
            return name
    return "낯섦"


def compute_affinity_delta(text: str) -> int:
    lowered = (text or "").lower()
    delta = 1
    if any(cue in lowered for cue in POSITIVE_CUES):
        delta += 2
    if any(cue in lowered for cue in NEGATIVE_CUES):
        delta -= 2
    if len(lowered) >= 40:
        delta += 1
    return max(-3, min(4, delta))


def build_context(
    state: RelationshipState,
    text: str,
    notes: list[UserNote] | None = None,
) -> ConditionContext:
    return ConditionContext(
        turn_count=state.turn_count,
        affinity=state.affinity,
        trust=state.trust,
        stage=state.stage,
        chapter=state.chapter,
        flags=dict(state.flags or {}),
        text=text,
        note_keys={note.key for note in (notes or [])},
        note_categories={note.category for note in (notes or [])},
    )


async def get_or_create_state(
    db: AsyncSession, conversation_id: str
) -> RelationshipState:
    state = (
        await db.execute(
            select(RelationshipState).where(
                RelationshipState.conversation_id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if state is None:
        state = RelationshipState(conversation_id=conversation_id)
        db.add(state)
        await db.flush()
    return state


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


async def advance_state(
    db: AsyncSession,
    conversation: Conversation,
    state: RelationshipState,
    *,
    text: str,
    notes: list[UserNote] | None = None,
    disclosed: bool = False,
) -> StoryAdvance:
    """턴 진행에 따른 상태 갱신 + 스토리 이벤트/엔딩 판정."""
    advance = StoryAdvance()
    if conversation.status == "completed" or state.ending_code:
        return advance

    state.turn_count += 1
    state.affinity = _clamp(state.affinity + compute_affinity_delta(text))
    if disclosed:
        state.trust = _clamp(state.trust + 2)
    else:
        state.trust = _clamp(state.trust + 1)
    state.stage = stage_for(state.affinity)

    story_defs = (
        await db.execute(
            select(StoryEventDef)
            .where(
                StoryEventDef.persona_id == conversation.persona_id,
                StoryEventDef.is_active.is_(True),
            )
            .order_by(StoryEventDef.sort_order, StoryEventDef.code)
        )
    ).scalars().all()
    fired_codes = set(
        (
            await db.execute(
                select(ConversationEventLog.code).where(
                    ConversationEventLog.conversation_id == conversation.id,
                    ConversationEventLog.kind == "story",
                )
            )
        ).scalars().all()
    )

    for definition in story_defs:
        if definition.code in fired_codes:
            continue
        ctx = build_context(state, text, notes)
        ctx.chapter = max(ctx.chapter, definition.chapter)
        if not evaluate(definition.conditions, ctx):
            continue

        effects = definition.effects or {}
        state.affinity = _clamp(state.affinity + int(effects.get("affinity", 0)))
        state.trust = _clamp(state.trust + int(effects.get("trust", 0)))
        if "chapter" in effects:
            state.chapter = int(effects["chapter"])
        for flag, value in (effects.get("flags") or {}).items():
            state.flags = {**(state.flags or {}), flag: bool(value)}
        state.stage = stage_for(state.affinity)

        db.add(
            ConversationEventLog(
                conversation_id=conversation.id,
                kind="story",
                code=definition.code,
                payload={"title": definition.title, "chapter": state.chapter},
            )
        )
        advance.events.append(definition)
        if definition.narrative_hint:
            advance.hints.append(definition.narrative_hint)
        elif definition.description:
            advance.hints.append(definition.description)
        fired_codes.add(definition.code)
        break  # 한 턴에 이벤트 하나

    if not advance.events:
        return advance

    ending_defs = (
        await db.execute(
            select(EndingDef)
            .where(
                EndingDef.persona_id == conversation.persona_id,
                EndingDef.is_active.is_(True),
            )
            .order_by(EndingDef.sort_order, EndingDef.code)
        )
    ).scalars().all()

    for ending in ending_defs:
        ctx = build_context(state, text, notes)
        if not evaluate(ending.conditions, ctx):
            continue
        state.ending_code = ending.code
        conversation.status = "completed"
        db.add(
            ConversationEventLog(
                conversation_id=conversation.id,
                kind="ending",
                code=ending.code,
                payload={"title": ending.title, "description": ending.description},
            )
        )
        advance.ending = ending
        break

    return advance
