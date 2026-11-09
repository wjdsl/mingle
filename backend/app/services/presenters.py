"""ORM → API 응답 변환 헬퍼."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Persona, RelationshipState
from app.schemas.chat import (
    ChatResponse,
    CTAOut,
    EndingOut,
    SourceOut,
    StoryEventOut,
    TriggerOut,
)
from app.schemas.conversation import (
    ConversationDetail,
    ConversationSummary,
    StateOut,
)
from app.services.chat_service import ChatOutcome


def state_out(state: RelationshipState | None) -> StateOut:
    if state is None:
        return StateOut(
            turn_count=0,
            affinity=10,
            trust=0,
            stage="낯섦",
            chapter=1,
            flags={},
            ending_code=None,
            updated_at=None,
        )
    return StateOut.model_validate(state)


def conversation_summary(
    conversation: Conversation,
    persona: Persona,
    state: RelationshipState | None,
) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        persona_id=persona.id,
        persona_slug=persona.slug,
        persona_name=persona.name,
        avatar_emoji=persona.avatar_emoji,
        theme_color=persona.theme_color,
        title=conversation.title,
        status=conversation.status,
        turn_count=state.turn_count if state else 0,
        affinity=state.affinity if state else 0,
        stage=state.stage if state else "낯섦",
        ending_code=state.ending_code if state else None,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


def conversation_detail(
    conversation: Conversation,
    persona: Persona,
    state: RelationshipState | None,
    *,
    message_count: int = 0,
    ending_title: str | None = None,
) -> ConversationDetail:
    summary = conversation_summary(conversation, persona, state)
    return ConversationDetail(
        **summary.model_dump(),
        persona_tagline=persona.tagline,
        chapter=state.chapter if state else 1,
        trust=state.trust if state else 0,
        ending_title=ending_title,
        message_count=message_count,
    )


async def load_conversation_summaries(
    db: AsyncSession, session_id: str
) -> list[ConversationSummary]:
    rows = (
        await db.execute(
            select(Conversation, Persona, RelationshipState)
            .join(Persona, Persona.id == Conversation.persona_id)
            .outerjoin(
                RelationshipState,
                RelationshipState.conversation_id == Conversation.id,
            )
            .where(Conversation.session_id == session_id)
            .order_by(
                Conversation.last_message_at.desc().nullslast(),
                Conversation.created_at.desc(),
            )
        )
    ).all()
    return [
        conversation_summary(conversation, persona, state)
        for conversation, persona, state in rows
    ]


def chat_response(outcome: ChatOutcome) -> ChatResponse:
    triggers: list[TriggerOut] = []
    for hit in outcome.trigger_hits:
        cta_out = None
        if hit.cta is not None:
            cta_out = CTAOut(
                id=hit.cta.id,
                trigger_id=hit.cta.trigger_id,
                label=hit.cta.label,
                description=hit.cta.description,
                cta_type=hit.cta.cta_type,
                url=hit.cta.url,
                payload=hit.cta.payload or {},
            )
        triggers.append(
            TriggerOut(
                id=hit.trigger.id,
                code=hit.trigger.code,
                name=hit.trigger.name,
                description=hit.trigger.description,
                cta=cta_out,
            )
        )

    ending = None
    if outcome.ending is not None:
        ending = EndingOut(
            code=outcome.ending.code,
            title=outcome.ending.title,
            description=outcome.ending.description,
        )

    return ChatResponse(
        conversation_id=outcome.conversation.id,
        user_message_id=outcome.user_message.id,
        assistant_message_id=outcome.assistant_message.id,
        reply=outcome.reply,
        provider=outcome.provider,
        latency_ms=outcome.latency_ms,
        state=state_out(outcome.state),
        sources=[SourceOut(**chunk.as_dict()) for chunk in outcome.sources],
        triggers=triggers,
        story_events=[
            StoryEventOut(
                code=event.code,
                title=event.title,
                description=event.description,
                narrative=event.narrative_hint or event.description,
            )
            for event in outcome.story_events
        ],
        ending=ending,
        notes_updated=outcome.notes_updated,
        guardrail_triggered=outcome.guardrail_triggered,
    )
