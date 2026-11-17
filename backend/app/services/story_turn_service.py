"""냉장고·구름섬 장면형 스토리 턴 처리.

푸르마/일반 페르소나용 `chat_service.process_message`와 분리한다.
관계 점수·RAG·User Note 추출·마케팅 Trigger는 이 작품들의 확정 규칙이 아니므로 사용하지 않는다.

한 턴의 처리 순서
1. 같은 request_id 기록이 있으면 저장된 응답을 그대로 반환(재시도 중복 방지)
2. 서버 진행 턴과 요청 턴이 다르면 409
3. 선택지 ID/문장 검증, 개인정보 마스킹
4. 장면 카드 + 이전 장면 맥락으로 프롬프트 구성 → LLM(JSON) 호출, 형식 오류 시 1회 재시도
5. 출력 검증·가드레일 → 사용자/캐릭터 메시지와 턴 장부를 한 트랜잭션으로 저장
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Conversation, Message, Persona, StoryTurnRecord, UserSession, utcnow
from app.services.chat_service import _BLOCKED_PATTERNS
from app.services.llm import LLMError, get_llm
from app.services.story_prompt import build_story_messages
from app.services.story_response_control import correction_note, validate_lines
from app.services.story_scenes import Scene, SceneChoice, SceneLine, StoryProjectDef, get_project, project_for_slug

logger = logging.getLogger(__name__)

MOCK_STORY_MODEL = "mock-story-v1"
MAX_REPLY_CHARS = 400
MAX_REACTION_CHARS = 16
MAX_ATTEMPTS = 2  # 형식·응답 제어 위반 시 1회 재생성
FIXED_PROVIDER = "fixed"
FIXED_MODEL = "scene-script"

_PHONE = re.compile(r"(?<!\d)(?:\+?82[- ]?)?0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGITS = re.compile(r"\d{6,}")
_DISPLAY = re.compile(r"\[디스플레이:[^\]]*\]")


class StoryTurnError(Exception):
    def __init__(self, status_code: int, detail: str, **extra) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.extra = extra


@dataclass(slots=True)
class ReplyLine:
    speaker: str
    text: str


@dataclass(slots=True)
class StoryTurnOutcome:
    conversation: Conversation
    project: StoryProjectDef
    record: StoryTurnRecord
    lines: list[ReplyLine]
    reaction: str
    completed_turns: int
    replayed: bool
    guardrail_triggered: bool


# --------------------------------------------------------------------------- #
# 입력 정리
# --------------------------------------------------------------------------- #
def mask_personal_info(text: str) -> str:
    """연락처·이메일·긴 숫자열을 저장/전송 전에 가린다 (바이블 개인정보 규칙)."""
    text = _EMAIL.sub("[이메일 생략]", text)
    text = _PHONE.sub("[연락처 생략]", text)
    return _LONG_DIGITS.sub("[숫자 생략]", text)


def safe_nickname(raw: str | None, fallback: str) -> str:
    value = " ".join((raw or "").split())[:20]
    if not value or mask_personal_info(value) != value or any(ch in value for ch in "{}[]<>"):
        return fallback
    return value


# --------------------------------------------------------------------------- #
# 대화 생성 / 조회
# --------------------------------------------------------------------------- #
async def ensure_story_persona(db: AsyncSession, project: StoryProjectDef) -> Persona:
    """대화 FK와 대시보드 집계용 페르소나 행. 일반 /api/chat 경로에서 쓰지 못하도록 비활성으로 둔다."""
    persona = (
        await db.execute(select(Persona).where(Persona.slug == project.persona_slug))
    ).scalar_one_or_none()
    if persona is None:
        persona = Persona(
            slug=project.persona_slug,
            name=project.persona_name,
            tagline=project.title,
            category="자체 제작",
            description=f"{project.title} 장면형 스토리 (story-chat API 전용)",
            is_active=False,
            sort_order=100,
        )
        db.add(persona)
        try:
            await db.flush()
        except IntegrityError:  # 동시 생성
            await db.rollback()
            persona = (
                await db.execute(select(Persona).where(Persona.slug == project.persona_slug))
            ).scalar_one()
    return persona


async def create_story_conversation(
    db: AsyncSession, session: UserSession, project: StoryProjectDef
) -> Conversation:
    session_id = session.id  # 아래 rollback 가능성에 대비해 먼저 읽어 둔다
    persona = await ensure_story_persona(db, project)
    conversation = Conversation(
        session_id=session_id,
        persona_id=persona.id,
        title=project.title[:200],
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def resolve_project(db: AsyncSession, conversation: Conversation) -> StoryProjectDef:
    persona = await db.get(Persona, conversation.persona_id)
    project = project_for_slug(persona.slug) if persona else None
    if project is None:
        raise StoryTurnError(404, "장면형 스토리 대화가 아닙니다.")
    return project


async def count_completed(db: AsyncSession, conversation_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(StoryTurnRecord)
            .where(StoryTurnRecord.conversation_id == conversation_id)
        )
        or 0
    )


async def load_records(db: AsyncSession, conversation_id: str) -> list[StoryTurnRecord]:
    return list(
        (
            await db.execute(
                select(StoryTurnRecord)
                .where(StoryTurnRecord.conversation_id == conversation_id)
                .order_by(StoryTurnRecord.turn_index)
            )
        ).scalars()
    )


# --------------------------------------------------------------------------- #
# 출력 검증
# --------------------------------------------------------------------------- #
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_story_output(project: StoryProjectDef, raw: str) -> tuple[list[ReplyLine], str]:
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("JSON 아님") from exc
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise ValueError("lines 없음")
    lines: list[ReplyLine] = []
    for item in data["lines"][: project.max_lines]:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker", "")).strip()
        text = " ".join(str(item.get("text", "")).split()) if project.id == "cloud" else str(item.get("text", "")).strip()
        if speaker not in project.speakers:
            if project.max_lines == 1:
                speaker = project.speakers[0]
            else:
                continue
        if text.startswith(f"{speaker}:"):
            text = text[len(speaker) + 1 :].strip()
        if project.id == "fridge":
            # 디스플레이 지문은 한 턴에 최대 1개 (첫 번째만 유지)
            first = _DISPLAY.search(text)
            if first:
                text = (first.group(0) + "\n" + _DISPLAY.sub("", text).strip()).strip()
        if text:
            lines.append(ReplyLine(speaker, text[:MAX_REPLY_CHARS]))
    if not lines:
        raise ValueError("유효한 대사 없음")
    reaction = " ".join(str(data.get("reaction", "")).split())[:MAX_REACTION_CHARS] or "이야기가 이어져요"
    return lines, reaction


def apply_story_guardrail(project: StoryProjectDef, lines: list[ReplyLine]) -> tuple[list[ReplyLine], bool]:
    if not settings.guardrail_enabled:
        return lines, False
    joined = " ".join(line.text for line in lines).lower()
    if any(pattern in joined for pattern in _BLOCKED_PATTERNS):
        logger.warning("스토리 가드레일 작동: project=%s", project.id)
        speaker, text = project.guardrail_reply
        return [ReplyLine(speaker, text)], True
    return lines, False


def _mock_reply(project: StoryProjectDef, scene: Scene, choice: SceneChoice | None) -> tuple[list[ReplyLine], str]:
    text = choice.reference_reply if choice else scene.default_reply
    speaker = next((s for s in project.speakers if text.startswith(f"{s}: ")), scene.opening_speaker)
    if text.startswith(f"{speaker}: "):
        text = text[len(speaker) + 2 :]
    return [ReplyLine(speaker, text)], choice.reaction if choice else "이야기가 이어져요"


def serialize_lines(lines: list[ReplyLine], reaction: str) -> str:
    return json.dumps(
        {"lines": [{"speaker": line.speaker, "text": line.text} for line in lines], "reaction": reaction},
        ensure_ascii=False,
    )


def deserialize_reply(message: Message) -> tuple[list[ReplyLine], str]:
    extra = message.extra or {}
    lines = [ReplyLine(item["speaker"], item["text"]) for item in extra.get("lines", [])]
    if not lines:
        lines = [ReplyLine(extra.get("speaker", ""), message.content)]
    return lines, extra.get("reaction", "")


# --------------------------------------------------------------------------- #
# 턴 처리
# --------------------------------------------------------------------------- #
async def _replay(
    db: AsyncSession, conversation: Conversation, project: StoryProjectDef, record: StoryTurnRecord
) -> StoryTurnOutcome:
    message = await db.get(Message, record.assistant_message_id)
    lines, reaction = deserialize_reply(message) if message else ([], "")
    return StoryTurnOutcome(
        conversation=conversation,
        project=project,
        record=record,
        lines=lines,
        reaction=reaction,
        completed_turns=await count_completed(db, conversation.id),
        replayed=True,
        guardrail_triggered=bool(message and (message.extra or {}).get("guardrail")),
    )


async def _find_by_request(db: AsyncSession, conversation_id: str, request_id: str) -> StoryTurnRecord | None:
    return (
        await db.execute(
            select(StoryTurnRecord).where(
                StoryTurnRecord.conversation_id == conversation_id,
                StoryTurnRecord.request_id == request_id,
            )
        )
    ).scalar_one_or_none()




def parse_intent(raw: str, scene: Scene) -> str | None:
    """분석 기록용 의도 ID. 장면에 정의된 ID가 아니면 버린다(점수에는 쓰지 않는다)."""
    try:
        value = json.loads(_strip_fences(raw)).get("intent_id")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    allowed = {it.id for it in scene.intents}
    return value if isinstance(value, str) and value in allowed else None


def _fill_nickname(text: str, nickname: str) -> str:
    return text.replace("[호칭]", nickname).replace("[닉네임]", nickname)


def fixed_reply_lines(project: StoryProjectDef, lines: tuple[SceneLine, ...], nickname: str) -> list[ReplyLine]:
    """장면 데이터의 고정 대사를 응답 줄로 변환한다(냉장고 디스플레이·구름섬 지문 표기 유지)."""
    from app.services.story_scene_sets import format_line

    return [ReplyLine(line.speaker, _fill_nickname(format_line(line, project.id), nickname)) for line in lines]


@dataclass(slots=True)
class GeneratedReply:
    lines: list[ReplyLine]
    reaction: str
    provider: str
    model: str
    latency_ms: int
    intent_id: str | None
    attempts: int
    violations: list[str]
    prompt_versions: dict[str, str]


async def _generate(
    project: StoryProjectDef,
    turn: int,
    nickname: str,
    history: list[tuple[int, str, str]],
    user_text: str,
    choice: SceneChoice | None,
    previous_replies: list[str],
) -> GeneratedReply:
    scene = project.scenes[turn]
    llm = get_llm()
    if llm.name == "mock":
        lines, reaction = _mock_reply(project, scene, choice)
        return GeneratedReply(lines, reaction, "mock", MOCK_STORY_MODEL, 0, None, 0, [], {})
    started = time.perf_counter()
    correction: str | None = None
    seen: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        messages, versions = build_story_messages(project, nickname, turn, history, user_text, choice, correction)
        result = await llm.generate(
            messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            json_mode=True,
        )
        try:
            lines, reaction = parse_story_output(project, result.text)
        except ValueError:
            logger.warning("스토리 응답 형식 오류: project=%s provider=%s attempt=%d", project.id, result.provider, attempt)
            correction = "JSON 형식이 아니었다. 출력 형식의 JSON 객체 하나만 출력한다."
            seen.append("format")
            continue
        violations = validate_lines(project, turn, [(l.speaker, l.text) for l in lines], previous_replies, nickname)
        if not violations:
            latency = int((time.perf_counter() - started) * 1000)
            return GeneratedReply(lines, reaction, result.provider, result.model, latency, parse_intent(result.text, scene), attempt, seen, versions)
        seen += [v.code for v in violations]
        logger.warning("스토리 응답 제어 위반: project=%s turn=%d attempt=%d codes=%s", project.id, turn, attempt, ",".join(v.code for v in violations))
        correction = correction_note(violations)
    raise LLMError(f"스토리 응답 검증 실패: {','.join(seen)}")


async def _history(db: AsyncSession, conversation_id: str) -> tuple[list[tuple[int, str, str]], list[str]]:
    history: list[tuple[int, str, str]] = []
    previous: list[str] = []
    for record in await load_records(db, conversation_id):
        user_msg = await db.get(Message, record.user_message_id)
        reply_msg = await db.get(Message, record.assistant_message_id)
        if user_msg and reply_msg:
            lines, reaction = deserialize_reply(reply_msg)
            history.append((record.turn_index, user_msg.content, serialize_lines(lines, reaction)))
            previous += [line.text for line in lines]
    return history, previous


async def _check_turn(db: AsyncSession, conversation: Conversation, project: StoryProjectDef, request_id: str, turn: int) -> StoryTurnOutcome | None:
    """같은 요청이면 저장된 응답(재생), 진행 불가면 StoryTurnError, 진행 가능하면 None."""
    existing = await _find_by_request(db, conversation.id, request_id)
    if existing is not None:
        if existing.turn_index != turn:
            raise StoryTurnError(409, "같은 요청 ID가 다른 장면에 이미 사용되었습니다.", current_turn=await count_completed(db, conversation.id))
        return await _replay(db, conversation, project, existing)
    completed = await count_completed(db, conversation.id)
    if conversation.status == "completed" or completed >= project.total_turns:
        raise StoryTurnError(409, "이미 마지막 장면까지 진행한 대화입니다.", current_turn=completed)
    if turn != completed:
        raise StoryTurnError(409, "서버의 진행 장면과 요청한 장면이 다릅니다.", current_turn=completed)
    return None


async def _save_turn(
    db: AsyncSession,
    conversation: Conversation,
    project: StoryProjectDef,
    *,
    turn: int,
    request_id: str,
    choice_id: str | None,
    user_message: Message,
    lines: list[ReplyLine],
    reaction: str,
    provider: str,
    model: str,
    latency_ms: int,
    extra: dict,
    guardrail_triggered: bool,
) -> StoryTurnOutcome:
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="\n".join(f"{line.speaker}: {line.text}" for line in lines),
        provider=provider,
        latency_ms=latency_ms,
        extra={
            "kind": "story_reply",
            "story_turn": turn,
            "request_id": request_id,
            "model": model,
            "scene_set": project.scene_set,
            "lines": [{"speaker": line.speaker, "text": line.text} for line in lines],
            "reaction": reaction,
            "guardrail": guardrail_triggered,
            **extra,
        },
    )
    db.add_all([user_message, assistant_message])
    await db.flush()
    record = StoryTurnRecord(
        conversation_id=conversation.id,
        project=project.id,
        turn_index=turn,
        request_id=request_id,
        choice_id=choice_id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
    )
    db.add(record)
    conversation.last_message_at = utcnow()
    if turn + 1 >= project.total_turns:
        conversation.status = "completed"
    try:
        await db.commit()
    except IntegrityError:
        # 같은 장면/요청이 동시에 처리된 경우: 먼저 저장된 결과를 기준으로 한다.
        await db.rollback()
        await db.refresh(conversation)
        winner = await _find_by_request(db, conversation.id, request_id)
        if winner is not None:
            return await _replay(db, conversation, project, winner)
        raise StoryTurnError(409, "이 장면은 다른 요청으로 이미 진행되었습니다.", current_turn=await count_completed(db, conversation.id))
    return StoryTurnOutcome(
        conversation=conversation,
        project=project,
        record=record,
        lines=lines,
        reaction=reaction,
        completed_turns=turn + 1,
        replayed=False,
        guardrail_triggered=guardrail_triggered,
    )


async def process_story_turn(
    db: AsyncSession,
    session: UserSession,
    conversation: Conversation,
    *,
    request_id: str,
    turn: int,
    text: str,
    choice_id: str | None,
) -> StoryTurnOutcome:
    project = await resolve_project(db, conversation)
    replay = await _check_turn(db, conversation, project, request_id, turn)
    if replay is not None:
        return replay
    scene = project.scenes[turn]
    if scene.input_mode == "none":
        raise StoryTurnError(409, "이 장면은 입력 없이 고정 연출로 진행합니다. fixed-turns 경로를 사용하세요.", current_turn=turn)
    choice: SceneChoice | None = None
    if choice_id is not None:
        choice = next((c for c in scene.choices if c.id == choice_id), None)
        if choice is None or choice.label != text.strip():
            raise StoryTurnError(422, "현재 장면의 선택지가 아닙니다.")
    user_text = mask_personal_info(text.strip())
    nickname = safe_nickname(session.display_name, project.nickname_fallback)
    history, previous = await _history(db, conversation.id)

    # LLM 호출 동안 DB 트랜잭션(SQLite 잠금)을 잡고 있지 않는다.
    await db.commit()
    generated = await _generate(project, turn, nickname, history, user_text, choice, previous)
    lines, guardrail_triggered = apply_story_guardrail(project, generated.lines)
    appended = fixed_reply_lines(project, scene.follow_up_lines + scene.closing_lines, nickname) if not guardrail_triggered else []
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=user_text,
        extra={"kind": "story_input", "story_turn": turn, "request_id": request_id, "choice_id": choice_id},
    )
    return await _save_turn(
        db,
        conversation,
        project,
        turn=turn,
        request_id=request_id,
        choice_id=choice_id,
        user_message=user_message,
        lines=lines + appended,
        reaction=generated.reaction,
        provider=generated.provider,
        model=generated.model,
        latency_ms=generated.latency_ms,
        extra={
            "intent_id": generated.intent_id,
            "attempts": generated.attempts,
            "control_violations": generated.violations,
            "fixed_lines_appended": len(appended),
            "prompt_data_versions": generated.prompt_versions,
        },
        guardrail_triggered=guardrail_triggered,
    )


async def process_fixed_turn(
    db: AsyncSession,
    session: UserSession,
    conversation: Conversation,
    *,
    request_id: str,
    turn: int,
) -> StoryTurnOutcome:
    """입력 없는 장면(냉장고·구름섬 10턴 예고편)을 LLM 없이 장면 데이터의 고정 연출로 진행한다."""
    project = await resolve_project(db, conversation)
    replay = await _check_turn(db, conversation, project, request_id, turn)
    if replay is not None:
        return replay
    scene = project.scenes[turn]
    if scene.input_mode != "none" or not scene.fixed_lines:
        raise StoryTurnError(409, "이 장면은 사용자 입력이 필요합니다.", current_turn=turn)
    nickname = safe_nickname(session.display_name, project.nickname_fallback)
    lines = fixed_reply_lines(project, scene.fixed_lines, nickname)
    marker = Message(
        conversation_id=conversation.id,
        role="system",
        content="(입력 없는 고정 장면)",
        extra={"kind": "story_fixed_scene", "story_turn": turn, "request_id": request_id},
    )
    return await _save_turn(
        db,
        conversation,
        project,
        turn=turn,
        request_id=request_id,
        choice_id=None,
        user_message=marker,
        lines=lines,
        reaction="",
        provider=FIXED_PROVIDER,
        model=FIXED_MODEL,
        latency_ms=0,
        extra={"source_level": scene.source_level},
        guardrail_triggered=False,
    )
