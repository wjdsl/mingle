"""Marketing Trigger 판정 및 CTA 노출.

규칙 조건(턴 수·키워드·관계 단계·플래그 등)을 1차로 평가하고,
TRIGGER_LLM_JUDGE_ENABLED=true 인 경우 LLM 판정을 추가로 요구한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    CTADef,
    Conversation,
    MarketingEvent,
    MarketingTriggerDef,
    RelationshipState,
    UserNote,
)
from app.services.conditions import evaluate
from app.services.llm import LLMError, get_llm
from app.services.story import build_context

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TriggerHit:
    trigger: MarketingTriggerDef
    cta: CTADef | None


async def evaluate_triggers(
    db: AsyncSession,
    conversation: Conversation,
    state: RelationshipState,
    text: str,
    notes: list[UserNote] | None = None,
) -> list[TriggerHit]:
    triggers = (
        await db.execute(
            select(MarketingTriggerDef)
            .where(
                MarketingTriggerDef.persona_id == conversation.persona_id,
                MarketingTriggerDef.is_active.is_(True),
            )
            .order_by(MarketingTriggerDef.priority.desc(), MarketingTriggerDef.code)
        )
    ).scalars().all()
    if not triggers:
        return []

    events = (
        await db.execute(
            select(MarketingEvent).where(
                MarketingEvent.conversation_id == conversation.id,
                MarketingEvent.event_type == "impression",
            )
        )
    ).scalars().all()
    fired: dict[str, list[MarketingEvent]] = {}
    for event in events:
        fired.setdefault(event.trigger_id, []).append(event)

    ctx = build_context(state, text, notes)
    ctas = (
        await db.execute(
            select(CTADef)
            .where(
                CTADef.trigger_id.in_([trigger.id for trigger in triggers]),
                CTADef.is_active.is_(True),
            )
            .order_by(CTADef.sort_order, CTADef.label)
        )
    ).scalars().all()
    cta_by_trigger: dict[str, CTADef] = {}
    for cta in ctas:
        cta_by_trigger.setdefault(cta.trigger_id, cta)

    for trigger in triggers:
        history = fired.get(trigger.id, [])
        if len(history) >= trigger.max_fires:
            continue
        if history:
            last_turn = max(int((event.extra or {}).get("turn", 0)) for event in history)
            if state.turn_count - last_turn < trigger.cooldown_turns:
                continue
        if not evaluate(trigger.conditions, ctx):
            continue
        if trigger.use_llm_judge and settings.trigger_llm_judge_enabled:
            if not await _llm_judge(trigger, text):
                continue

        cta = cta_by_trigger.get(trigger.id)
        db.add(
            MarketingEvent(
                conversation_id=conversation.id,
                trigger_id=trigger.id,
                cta_id=cta.id if cta else None,
                event_type="impression",
                extra={"turn": state.turn_count, "stage": state.stage},
            )
        )
        return [TriggerHit(trigger=trigger, cta=cta)]

    return []


async def _llm_judge(trigger: MarketingTriggerDef, text: str) -> bool:
    prompt = (
        "아래 대화 발화가 마케팅 트리거의 의도를 충족하는지 판단하세요.\n"
        f"트리거: {trigger.name} - {trigger.description}\n"
        f"발화: {text}\n"
        "충족하면 YES, 아니면 NO 만 출력하세요."
    )
    try:
        result = await get_llm().generate(
            [{"role": "system", "content": "너는 이진 분류기다. YES 또는 NO만 출력한다."},
             {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=5,
        )
    except LLMError as exc:
        logger.warning("Trigger LLM 판정 실패: %s", exc)
        return False
    return result.text.strip().upper().startswith("Y")


async def record_click(
    db: AsyncSession, conversation_id: str, cta_id: str, metadata: dict | None = None
) -> MarketingEvent:
    cta = await db.get(CTADef, cta_id)
    if cta is None:
        raise ValueError("존재하지 않는 CTA입니다.")
    event = MarketingEvent(
        conversation_id=conversation_id,
        trigger_id=cta.trigger_id,
        cta_id=cta.id,
        event_type="click",
        extra=metadata or {},
    )
    db.add(event)
    await db.flush()
    return event
