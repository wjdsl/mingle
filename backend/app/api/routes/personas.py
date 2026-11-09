"""페르소나 조회."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import Conversation, Persona, PersonaKnowledge
from app.schemas.persona import PersonaDetail, PersonaSummary

router = APIRouter(prefix="/personas", tags=["personas"])


@router.get("", response_model=list[PersonaSummary], summary="페르소나 목록")
async def list_personas(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Persona)
            .where(Persona.is_active.is_(True))
            .order_by(Persona.sort_order, Persona.name)
        )
    ).scalars().all()
    return rows


@router.get("/{slug}", response_model=PersonaDetail, summary="페르소나 상세")
async def get_persona(slug: str, db: AsyncSession = Depends(get_db)):
    persona = (
        await db.execute(select(Persona).where(Persona.slug == slug))
    ).scalar_one_or_none()
    if persona is None or not persona.is_active:
        raise HTTPException(status_code=404, detail="페르소나를 찾을 수 없습니다.")

    knowledge_count = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(PersonaKnowledge)
                .where(PersonaKnowledge.persona_id == persona.id)
            )
        )
        or 0
    )
    conversation_count = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.persona_id == persona.id)
            )
        )
        or 0
    )

    detail = PersonaDetail.model_validate(persona)
    detail.knowledge_count = knowledge_count
    detail.conversation_count = conversation_count
    return detail
