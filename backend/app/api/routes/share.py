"""결과/엔딩 공유 카드."""

from __future__ import annotations

import secrets

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import get_db
from app.db.models import (
    Conversation,
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
    if card is None or card.revoked or not card.is_public:
        raise HTTPException(status_code=404, detail="공유 카드를 찾을 수 없습니다.")
    # 조회수 원자 갱신: 동시 요청에서도 누락 없이 증가한다.
    await db.execute(
        update(ShareCard).where(ShareCard.id == card.id).values(views=ShareCard.views + 1)
    )
    await db.commit()
    await db.refresh(card)
    return _card_out(card)


@router.post(
    "/conversations/{conversation_id}/share/revoke",
    summary="공유 카드 폐기 (대화 기준)",
)
async def revoke_share_by_conversation(
    conversation_id: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    card = (
        await db.execute(
            select(ShareCard)
            .where(ShareCard.conversation_id == conversation.id)
            .order_by(ShareCard.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="공유 카드를 찾을 수 없습니다.")
    card.revoked = True
    card.revoked_at = datetime.now(timezone.utc)
    card.is_public = False
    await db.commit()
    return {"revoked": True, "slug": card.slug}


@router.delete("/share/{slug}", summary="공유 카드 폐기")
async def revoke_share(
    slug: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    card = (
        await db.execute(select(ShareCard).where(ShareCard.slug == slug))
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="공유 카드를 찾을 수 없습니다.")
    # 소유자 확인
    conversation = await db.get(Conversation, card.conversation_id)
    if conversation is None or conversation.session_id != session.id:
        raise HTTPException(status_code=403, detail="공유 카드를 폐기할 권한이 없습니다.")
    card.revoked = True
    card.revoked_at = datetime.now(timezone.utc)
    card.is_public = False
    await db.commit()
    return {"revoked": True, "slug": slug}


def _card_out(card: ShareCard) -> dict:
    return {
        "slug": card.slug,
        "title": card.title,
        "summary": card.summary,
        "payload": card.payload,
        "views": card.views,
        "created_at": card.created_at,
    }
