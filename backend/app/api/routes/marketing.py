"""마케팅 CTA 클릭 추적 / 노출 이력."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import get_db
from app.db.models import MarketingEvent, UserSession
from app.schemas.marketing import MarketingEventOut, TrackEventRequest
from app.services.marketing import record_click

router = APIRouter(tags=["marketing"])


@router.post(
    "/marketing/events",
    response_model=MarketingEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="CTA 클릭 기록",
)
async def track_event(
    payload: TrackEventRequest,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(
        db, session.id, payload.conversation_id
    )
    try:
        event = await record_click(
            db, conversation.id, payload.cta_id, payload.metadata
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return event


@router.get(
    "/conversations/{conversation_id}/marketing-events",
    response_model=list[MarketingEventOut],
    summary="대화의 마케팅 노출/클릭 이력",
)
async def list_events(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    rows = (
        await db.execute(
            select(MarketingEvent)
            .where(MarketingEvent.conversation_id == conversation.id)
            .order_by(MarketingEvent.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return rows
