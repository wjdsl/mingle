"""비회원 세션 / 개인 코드 발급·복구."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session
from app.core.security import (
    generate_personal_code,
    hash_personal_code,
    normalize_personal_code,
)
from app.db.base import get_db
from app.db.models import Persona, UserSession, utcnow
from app.schemas.conversation import ConversationSummary
from app.schemas.session import ResumeRequest, SessionCreate, SessionCreated, SessionOut
from app.services.chat_service import create_conversation
from app.services.presenters import (
    conversation_summary,
    load_conversation_summaries,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _get_persona(db: AsyncSession, slug: str) -> Persona:
    persona = (
        await db.execute(
            select(Persona).where(Persona.slug == slug, Persona.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=404, detail="페르소나를 찾을 수 없습니다.")
    return persona


@router.post(
    "",
    response_model=SessionCreated,
    status_code=status.HTTP_201_CREATED,
    summary="비회원 세션 생성 (선택: 개인 코드 발급)",
)
async def create_session(
    payload: SessionCreate, db: AsyncSession = Depends(get_db)
) -> SessionCreated:
    code = generate_personal_code()
    session = UserSession(
        code_hash=hash_personal_code(code),
        code_hint=normalize_personal_code(code)[-4:],
        display_name=payload.display_name,
    )
    db.add(session)
    await db.flush()

    conversation_payload: dict | None = None
    if payload.persona_slug:
        persona = await _get_persona(db, payload.persona_slug)
        conversation, state = await create_conversation(
            db, session_id=session.id, persona=persona
        )
        conversation_payload = conversation_summary(
            conversation, persona, state
        ).model_dump(mode="json")

    await db.commit()
    return SessionCreated(
        session=SessionOut.model_validate(session),
        personal_code=code,
        conversation=conversation_payload,
        conversations=[conversation_payload] if conversation_payload else [],
    )


@router.post(
    "/resume",
    response_model=SessionCreated,
    summary="개인 코드로 세션·대화 이어하기",
)
async def resume_session(
    payload: ResumeRequest, db: AsyncSession = Depends(get_db)
) -> SessionCreated:
    digest = hash_personal_code(payload.personal_code)
    session = (
        await db.execute(
            select(UserSession).where(
                UserSession.code_hash == digest,
                UserSession.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="개인 코드를 확인해 주세요.",
        )

    session.last_seen_at = utcnow()
    summaries = await load_conversation_summaries(db, session.id)
    await db.commit()

    return SessionCreated(
        session=SessionOut.model_validate(session),
        personal_code=normalize_personal_code(payload.personal_code),
        conversation=summaries[0].model_dump(mode="json") if summaries else None,
        conversations=[summary.model_dump(mode="json") for summary in summaries],
    )


@router.get("/me", response_model=SessionOut, summary="현재 세션 정보")
async def get_me(session: UserSession = Depends(get_current_session)):
    return session


@router.get(
    "/me/conversations",
    response_model=list[ConversationSummary],
    summary="내 대화 목록",
)
async def list_my_conversations(
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    return await load_conversation_summaries(db, session.id)
