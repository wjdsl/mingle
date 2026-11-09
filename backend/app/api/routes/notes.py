"""User Note 조회/수동 편집."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session
from app.db.base import get_db
from app.db.models import Persona, UserNote, UserSession, utcnow
from app.schemas.conversation import NoteCreate, NoteOut, NoteUpdate
from app.services.memory import load_notes

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=list[NoteOut], summary="내 기억(User Note) 목록")
async def list_notes(
    persona_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    return await load_notes(db, session.id, persona_id, limit=limit)


@router.post(
    "",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
    summary="기억 수동 추가/갱신",
)
async def upsert_note(
    payload: NoteCreate,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    if payload.persona_id and await db.get(Persona, payload.persona_id) is None:
        raise HTTPException(status_code=404, detail="페르소나를 찾을 수 없습니다.")

    existing = (
        await db.execute(
            select(UserNote).where(
                UserNote.session_id == session.id,
                UserNote.key == payload.key,
                UserNote.persona_id == payload.persona_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        note = UserNote(
            session_id=session.id,
            persona_id=payload.persona_id,
            key=payload.key,
            value=payload.value,
            category=payload.category,
            importance=payload.importance,
            confidence=1.0,
            source="manual",
        )
        db.add(note)
    else:
        existing.value = payload.value
        existing.category = payload.category
        existing.importance = payload.importance
        existing.source = "manual"
        note = existing

    await db.commit()
    return note


@router.patch("/{note_id}", response_model=NoteOut, summary="기억 수정")
async def update_note(
    note_id: str,
    payload: NoteUpdate,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    note = await _get_owned_note(db, session.id, note_id)
    note.value = payload.value
    if payload.importance is not None:
        note.importance = payload.importance
    note.updated_at = utcnow()
    await db.commit()
    return note


@router.delete(
    "/{note_id}", status_code=status.HTTP_204_NO_CONTENT, summary="기억 삭제"
)
async def delete_note(
    note_id: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> None:
    note = await _get_owned_note(db, session.id, note_id)
    await db.delete(note)
    await db.commit()


async def _get_owned_note(
    db: AsyncSession, session_id: str, note_id: str
) -> UserNote:
    note = (
        await db.execute(
            select(UserNote).where(
                UserNote.id == note_id, UserNote.session_id == session_id
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="기억을 찾을 수 없습니다.")
    return note
