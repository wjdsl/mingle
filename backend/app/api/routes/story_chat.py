"""냉장고·구름섬 장면형 스토리 대화 API.

세션은 기존 `POST /api/sessions`의 개인 코드(X-Personal-Code)를 그대로 사용한다.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_owned_conversation
from app.db.base import get_db
from app.db.models import UserSession
from app.schemas.story_chat import (
    SceneChoiceOut,
    SceneLineOut,
    SceneOut,
    SceneSet,
    SceneSetOut,
    StoryConversationCreate,
    StoryConversationOut,
    StoryFixedTurnRequest,
    StoryReplyLine,
    StoryTurnRequest,
    StoryTurnResponse,
)
from app.services.llm import LLMError
from app.services.story_scenes import get_project
from app.services.story_turn_service import (
    StoryTurnError,
    StoryTurnOutcome,
    count_completed,
    create_story_conversation,
    process_fixed_turn,
    process_story_turn,
    resolve_project,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/story-chat", tags=["story-chat"])


def llm_failure_reason(exc: Exception) -> str:
    """로그용 원인 분류만 추출한다(오류 본문·사용자 입력·키는 남기지 않는다)."""
    message = str(exc)
    status = re.findall(r"Gemini 오류 (\d{3})", message)
    if status:
        return f"provider_http_{status[-1]}"
    if "검증 실패" in message:
        return "response_control:" + re.sub(r"[^a-z_,]", "", message.split(":", 1)[-1])[:80]
    if "연결 실패" in message:
        return "provider_connection"
    if "형식" in message:
        return "provider_response_format"
    return "provider_other"


def _http_error(exc: StoryTurnError) -> HTTPException:
    detail: dict | str = {"message": exc.detail, **exc.extra} if exc.extra else exc.detail
    return HTTPException(status_code=exc.status_code, detail=detail)


def _turn_response(outcome: StoryTurnOutcome) -> StoryTurnResponse:
    record = outcome.record
    return StoryTurnResponse(
        conversation_id=outcome.conversation.id,
        project=outcome.project.id,
        request_id=record.request_id,
        turn=record.turn_index,
        replies=[StoryReplyLine(speaker=line.speaker, text=line.text) for line in outcome.lines],
        reaction=outcome.reaction,
        provider=record.provider,
        model=record.model,
        latency_ms=record.latency_ms,
        completed_turns=outcome.completed_turns,
        total_turns=outcome.project.total_turns,
        finished=outcome.completed_turns >= outcome.project.total_turns,
        replayed=outcome.replayed,
        guardrail_triggered=outcome.guardrail_triggered,
    )


@router.post(
    "/conversations",
    response_model=StoryConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="냉장고·구름섬 장면형 대화 시작",
)
async def create_conversation(
    payload: StoryConversationCreate,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> StoryConversationOut:
    project = get_project(payload.project, payload.scene_set)
    if project is None:
        raise HTTPException(status_code=503, detail="장면 데이터를 읽을 수 없습니다. STORY_DATA_DIR와 data/ 파일을 확인해 주세요.")
    conversation = await create_story_conversation(db, session, project)
    await db.commit()
    return StoryConversationOut(
        conversation_id=conversation.id,
        project=project.id,
        completed_turns=0,
        total_turns=project.total_turns,
        finished=False,
        scene_set=project.scene_set,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=StoryConversationOut,
    summary="장면형 대화의 서버 진행 상태",
)
async def get_conversation(
    conversation_id: str,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> StoryConversationOut:
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    try:
        project = await resolve_project(db, conversation)
    except StoryTurnError as exc:
        raise _http_error(exc) from exc
    completed = await count_completed(db, conversation.id)
    return StoryConversationOut(
        conversation_id=conversation.id,
        project=project.id,
        completed_turns=completed,
        total_turns=project.total_turns,
        finished=completed >= project.total_turns,
        scene_set=project.scene_set,
    )


@router.get(
    "/scene-sets/{project_id}/{scene_set}",
    response_model=SceneSetOut,
    summary="장면 세트 조회 (화면 표시용 첫 대사·사건·선택지, 점수 제외)",
)
async def get_scene_set(project_id: str, scene_set: SceneSet) -> SceneSetOut:
    project = get_project(project_id, scene_set)
    if project is None:
        raise HTTPException(status_code=404, detail="작품 또는 장면 데이터를 찾을 수 없습니다.")
    scenes = []
    for index, scene in enumerate(project.scenes):
        opening = [SceneLineOut(speaker=l.speaker, text=l.text, direction=l.direction) for l in scene.opening_lines]
        if not opening and scene.input_mode == "input":
            opening = [SceneLineOut(speaker=scene.opening_speaker, text=scene.opening)]
        scenes.append(
            SceneOut(
                turn=index,
                title=scene.title,
                situation=scene.situation,
                input_mode=scene.input_mode,
                opening_lines=opening,
                system_messages=list(scene.system_messages) or ([scene.event] if scene.event else []),
                choices=[SceneChoiceOut(choice_id=c.id, label=c.label) for c in scene.choices],
                source_level=scene.source_level,
            )
        )
    note = (
        "시나리오 장면 카드 초안(팀 미확정). [호칭]/[닉네임]은 화면에서 사용자 호칭으로 바꿔 표시한다. 점수·관계 단계·판정은 포함하지 않는다."
        if scene_set == "scenario_draft_v1"
        else "현재 프론트 Mock 장면과 같은 기본 세트."
    )
    return SceneSetOut(project=project.id, scene_set=project.scene_set, total_turns=project.total_turns, scenes=scenes, note=note)


@router.post(
    "/conversations/{conversation_id}/fixed-turns",
    response_model=StoryTurnResponse,
    summary="입력 없는 고정 장면 진행 (예고편 등, LLM 호출 없음, request_id 멱등)",
)
async def send_fixed_turn(
    conversation_id: str,
    payload: StoryFixedTurnRequest,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> StoryTurnResponse:
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    try:
        outcome = await process_fixed_turn(db, session, conversation, request_id=payload.request_id, turn=payload.turn)
    except StoryTurnError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return _turn_response(outcome)


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=StoryTurnResponse,
    summary="현재 장면에 사용자 입력을 보내고 캐릭터 응답 받기 (request_id 멱등)",
)
async def send_turn(
    conversation_id: str,
    payload: StoryTurnRequest,
    session: UserSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> StoryTurnResponse:
    conversation = await get_owned_conversation(db, session.id, conversation_id)
    try:
        outcome = await process_story_turn(
            db,
            session,
            conversation,
            request_id=payload.request_id,
            turn=payload.turn,
            text=payload.input.text,
            choice_id=payload.input.choice_id,
        )
    except StoryTurnError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except LLMError as exc:
        await db.rollback()
        # 예외 원문에는 공급자 응답 일부가 있을 수 있어 분류만 기록한다.
        logger.warning(
            "스토리 LLM 호출 실패: conversation=%s type=%s reason=%s",
            conversation_id,
            type(exc).__name__,
            llm_failure_reason(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    return _turn_response(outcome)
