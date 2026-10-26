"""스토리 진행 타임라인."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import get_db
from app.db.models import ConversationEventLog, UserSession

router = APIRouter(prefix="/conversations", tags=["story"])


@router.get(
    "/{conversation_id}/timeline",
    summary="스토리 이벤트/엔딩 타임라인",
)
async def get_timeline(
    conversation_id: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    rows = (
        await db.execute(
            select(ConversationEventLog)
            .where(ConversationEventLog.conversation_id == conversation.id)
            .order_by(ConversationEventLog.created_at, ConversationEventLog.id)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "code": row.code,
            "title": (row.payload or {}).get("title", row.code),
            "payload": row.payload,
            "created_at": row.created_at,
        }
        for row in rows
    ]
