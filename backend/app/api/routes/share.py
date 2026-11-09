"""결과/엔딩 공유 카드."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import get_db
from app.db.models import (
    EndingDef,
    Message,
    Persona,
    RelationshipState,
    ShareCard,
    UserSession,
)
from app.services.story import get_or_create_state

router = APIRouter(tags=["share"])


class ShareCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=1000)
    include_messages: int = Field(default=6, ge=0, le=30)


@router.post(
    "/conversations/{conversation_id}/share",
    status_code=status.HTTP_201_CREATED,
    summary="공유 카드 생성 (기존 카드 재사용)",
)
async def create_share(
    conversation_id: str,
    payload: ShareCreate,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    persona = await db.get(Persona, conversation.persona_id)
    state = await get_or_create_state(db, conversation.id)

    messages = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(payload.include_messages)
        )
    ).scalars().all()

    ending = None
    if state.ending_code:
        ending_row = (
            await db.execute(
                select(EndingDef).where(
                    EndingDef.persona_id == persona.id,
                    EndingDef.code == state.ending_code,
                )
            )
        ).scalar_one_or_none()
        if ending_row is not None:
            ending = {
                "code": ending_row.code,
                "title": ending_row.title,
                "description": ending_row.description,
            }

    card = (
        await db.execute(
            select(ShareCard)
            .where(ShareCard.conversation_id == conversation.id)
            .order_by(ShareCard.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    card_payload = {
        "persona": {
            "name": persona.name,
            "tagline": persona.tagline,
            "avatar_emoji": persona.avatar_emoji,
            "theme_color": persona.theme_color,
        },
        "state": {
            "stage": state.stage,
            "affinity": state.affinity,
            "trust": state.trust,
            "chapter": state.chapter,
            "turn_count": state.turn_count,
        },
        "ending": ending,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in reversed(messages)
        ],
    }
    title = payload.title or f"{persona.name}와의 대화"
    summary = payload.summary or (
        f"{state.stage} 단계 · 호감도 {state.affinity} · {state.turn_count}턴"
    )

    if card is None:
        card = ShareCard(
            conversation_id=conversation.id,
            slug=secrets.token_urlsafe(8),
            title=title,
            summary=summary,
            payload=card_payload,
        )
        db.add(card)
    else:
        card.title = title
        card.summary = summary
        card.payload = card_payload

    await db.commit()
    return _card_out(card)


@router.get("/share/{slug}", summary="공유 카드 조회 (공개)")
async def get_share(slug: str, db: AsyncSession = Depends(get_db)):
    card = (
        await db.execute(select(ShareCard).where(ShareCard.slug == slug))
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="공유 카드를 찾을 수 없습니다.")
    card.views += 1
    await db.commit()
    return _card_out(card)


def _card_out(card: ShareCard) -> dict:
    return {
        "slug": card.slug,
        "title": card.title,
        "summary": card.summary,
        "payload": card.payload,
        "views": card.views,
        "created_at": card.created_at,
    }
