"""채팅 (일반 응답 / SSE 스트리밍)."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import SessionLocal, get_db
from app.db.models import Conversation, UserSession
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import (
    ConversationCompletedError,
    PersonaNotFoundError,
    process_message,
)
from app.services.llm import LLMError
from app.services.presenters import chat_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, summary="메시지 전송")
async def send_message(
    payload: ChatRequest,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    conversation = await get_owned_conversation(db, session.id, payload.conversation_id)
    if conversation.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 엔딩에 도달한 대화입니다. 새 대화를 시작해 주세요.",
        )

    try:
        outcome = await process_message(db, conversation, payload.message)
        await db.commit()
    except ConversationCompletedError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PersonaNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        await db.rollback()
        logger.warning("LLM 호출 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc

    return chat_response(outcome)


def _sse(event: str, data: dict | None) -> str:
    payload = json.dumps(data or {}, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post(
    "/stream",
    summary="메시지 전송 (SSE 스트리밍)",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "event: token (data: {token}), "
                "event: final (data: ChatResponse), "
                "event: error (data: {detail})"
            ),
        }
    },
)
async def stream_message(
    payload: ChatRequest,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    conversation = await get_owned_conversation(db, session.id, payload.conversation_id)
    if conversation.status == "completed":
        raise HTTPException(
            status_code=409,
            detail="이미 엔딩에 도달한 대화입니다. 새 대화를 시작해 주세요.",
        )
    conversation_id = conversation.id
    user_text = payload.message

    async def event_source():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(token: str) -> None:
            await queue.put(("token", {"token": token}))

        async def run() -> None:
            async with SessionLocal() as stream_db:
                try:
                    conv = await stream_db.get(Conversation, conversation_id)
                    if conv is None:
                        await queue.put(("error", {"detail": "대화를 찾을 수 없습니다."}))
                        return
                    outcome = await process_message(
                        stream_db, conv, user_text, emit=emit
                    )
                    await stream_db.commit()
                    await queue.put(
                        ("final", chat_response(outcome).model_dump(mode="json"))
                    )
                except ConversationCompletedError as exc:
                    await stream_db.rollback()
                    await queue.put(("error", {"detail": str(exc)}))
                except LLMError as exc:
                    await stream_db.rollback()
                    logger.warning("LLM 스트리밍 실패: %s", exc)
                    await queue.put(
                        (
                            "error",
                            {"detail": "AI 응답 생성에 실패했습니다. 다시 시도해 주세요."},
                        )
                    )
                except Exception as exc:  # pragma: no cover - 예상치 못한 오류
                    await stream_db.rollback()
                    logger.exception("스트리밍 처리 오류")
                    await queue.put(("error", {"detail": f"서버 오류: {exc}"}))
                finally:
                    await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield _sse(event, data)
        finally:
            await task

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
