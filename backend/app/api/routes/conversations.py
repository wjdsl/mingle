"""대화 생성/조회/메시지."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import get_db
from app.db.models import (
    Conversation,
    EndingDef,
    Message,
    Persona,
    RelationshipState,
    UserSession,
)
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    ConversationUpdate,
    MessageOut,
    StateOut,
)
from app.services.chat_service import create_conversation
from app.services.presenters import (
    conversation_detail,
    conversation_summary,
    load_conversation_summaries,
    state_out,
)
from app.services.story import get_or_create_state

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="새 대화 시작",
)
async def create(
    payload: ConversationCreate,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    persona = (
        await db.execute(
            select(Persona).where(
                Persona.slug == payload.persona_slug, Persona.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=404, detail="페르소나를 찾을 수 없습니다.")

    conversation, state = await create_conversation(
        db,
        session_id=session.id,
        persona=persona,
        title=payload.title,
    )
    await db.commit()
    return conversation_detail(conversation, persona, state, message_count=1)


@router.get("", response_model=list[ConversationSummary], summary="내 대화 목록")
async def list_conversations(
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    return await load_conversation_summaries(db, session.id)


@router.get("/{conversation_id}", response_model=ConversationDetail, summary="대화 상세")
async def get_conversation(
    conversation_id: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    persona = await db.get(Persona, conversation.persona_id)
    state = await get_or_create_state(db, conversation.id)
    message_count = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation.id)
            )
        )
        or 0
    )
    ending_title = None
    if state.ending_code:
        ending_title = (
            await db.execute(
                select(EndingDef.title).where(
                    EndingDef.persona_id == persona.id,
                    EndingDef.code == state.ending_code,
                )
            )
        ).scalar_one_or_none()
    return conversation_detail(
        conversation,
        persona,
        state,
        message_count=message_count,
        ending_title=ending_title,
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageOut],
    summary="메시지 목록 (오래된 순)",
)
async def list_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None, description="이 시각 이전 메시지"),
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    stmt = select(Message).where(Message.conversation_id == conversation.id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    rows = (
        await db.execute(
            stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


@router.get(
    "/{conversation_id}/state",
    response_model=StateOut,
    summary="관계·스토리 상태",
)
async def get_state(
    conversation_id: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    state = await get_or_create_state(db, conversation.id)
    await db.commit()
    return state_out(state)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationSummary,
    summary="대화 제목 변경",
)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    conversation.title = payload.title
    await db.commit()

    persona = await db.get(Persona, conversation.persona_id)
    state = (
        await db.execute(
            select(RelationshipState).where(
                RelationshipState.conversation_id == conversation.id
            )
        )
    ).scalar_one_or_none()
    return conversation_summary(conversation, persona, state)
