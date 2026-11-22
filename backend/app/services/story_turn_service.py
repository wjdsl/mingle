"""냉장고·구름섬 장면형 스토리 턴 처리.

푸르마/일반 페르소나용 `chat_service.process_message`와 분리한다.
관계 점수·RAG·User Note 추출·마케팅 Trigger는 이 작품들의 확정 규칙이 아니므로 사용하지 않는다.

한 턴의 처리 순서
1. 같은 request_id 기록이 있으면 저장된 응답을 그대로 반환(재시도 중복 방지)
2. 서버 진행 턴과 요청 턴이 다르면 409
3. 선택지 ID/문장 검증, 개인정보 마스킹
4. 장면 카드 + 이전 장면 맥락으로 프롬프트 구성 → LLM(JSON) 호출, 형식 오류 시 1회 재시도
   AI가 실패하면(공급자 503·429·시간 초과·응답 검증 실패 등) 장면의 고정 대사로 이어 간다(2026-11-22 팀 결정).
   저장 provider는 "fallback"이고 사유 코드는 로그와 메시지 extra에만 남긴다. 화면에는 표시하지 않는다.
5. 출력 검증·가드레일 → 사용자/캐릭터 메시지와 턴 장부를 한 트랜잭션으로 저장
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Conversation, Message, Persona, StoryTurnRecord, UserSession, utcnow
from app.services.chat_service import _BLOCKED_PATTERNS
from app.services.llm import LLMError, get_llm
from app.services.llm.gemini_provider import GeminiHTTPError, GeminiQuotaError, GeminiTimeoutError
from app.services.story_fallback_lines import FREE_INPUT_FALLBACK
from app.services.story_judgement import fridge_trailer_text, judge_conversation
from app.services.story_dialogue import DialogueInfo, info_from_extra, rewrite_fridge_dialogue
from app.services.story_prompt import build_story_messages
from app.services.story_safety import COMPANION_LINES, is_story_crisis
from app.services.story_response_control import correction_note, sentences, validate_lines
from app.services.story_scenes import Scene, SceneChoice, SceneLine, StoryProjectDef, fill_user, get_project, project_for_slug

logger = logging.getLogger(__name__)

MOCK_STORY_MODEL = "mock-story-v1"
MAX_REPLY_CHARS = 400
MAX_REACTION_CHARS = 16
MAX_ATTEMPTS = 2  # 형식·응답 제어 위반 시 1회 재생성
FIXED_PROVIDER = "fixed"
FIXED_MODEL = "scene-script"
# AI 실패 시 장면 고정 대사로 이어 간 턴. 턴 기록·메시지에 이 값으로 남겨 관리자 원문 조회·집계에서 구분한다.
FALLBACK_PROVIDER = "fallback"
FALLBACK_MODEL = "scene-fallback-v1"
DEFAULT_REACTION = "이야기가 이어져요"

_PHONE = re.compile(r"(?<!\d)(?:\+?82[- ]?)?0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGITS = re.compile(r"\d{6,}")
_DISPLAY = re.compile(r"\[디스플레이:[^\]]*\]")
# 응답 맨 앞 디스플레이 지문의 오염 표기만 표준형으로 고친다.
# 관측: '스' 자리에 가타카나 'ス'(U+30B9). 안전 변형: 반각 'ｽ'(U+FF7D), 전각 콜론, 콜론 앞뒤 공백 차이.
_DISPLAY_VARIANT = re.compile(r"^\[디[스スｽ]플레이\s*[:：]\s*([^\[\]\n]*)\]")


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
class StorySafetyOutcome:
    """위기 신호 입력의 결과. 턴 기록·메시지를 저장하지 않으며 장면은 그대로다."""

    conversation: Conversation
    project: StoryProjectDef
    request_id: str
    turn: int
    lines: list[ReplyLine]
    completed_turns: int


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
    dialogue: DialogueInfo | None = None  # 스토리/대사 생성 공급자 기록(냉장고 Qwen 하이브리드)


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


_SAFE_KEY = re.compile(r"^[A-Za-z_]{1,24}$")


def _key_names(value: dict) -> str:
    # 키 이름도 모델 생성 문자열이므로 짧은 영문 식별자만 남기고 나머지는 개수로 센다.
    names = sorted(key for key in value if _SAFE_KEY.match(str(key)))
    other = len(value) - len(names)
    return ",".join(names + ([f"other{other}"] if other else [])) or "-"


def describe_output_shape(raw: str | None) -> str:
    """형식 실패 진단용 구조 요약. 대사·값 원문은 포함하지 않는다."""
    if not isinstance(raw, str):
        return f"type={type(raw).__name__}"
    stripped = raw.strip()
    if not stripped:
        return "chars=0 start=empty"
    start = "fence" if stripped.startswith("```") else stripped[0] if stripped[0] in "{[" else "other"
    parts = [f"chars={len(raw)}", f"start={start}"]
    body = _strip_fences(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        # msg는 json 모듈의 고정 문구라 원문을 담지 않는다.
        parts.append(f"json=invalid({exc.msg}) at={exc.pos}/{len(body)}")
        return " ".join(parts)
    if isinstance(data, dict):
        parts.append(f"json=object keys={_key_names(data)}")
        lines = data.get("lines")
        if isinstance(lines, list):
            parts.append(f"lines=list[{len(lines)}]")
            first = lines[0] if lines else None
            if isinstance(first, dict):
                parts.append(f"line0_keys={_key_names(first)}")
            elif first is not None:
                parts.append(f"line0={type(first).__name__}")
        elif "lines" in data:
            parts.append(f"lines={type(lines).__name__}")
    elif isinstance(data, list):
        parts.append(f"json=array[{len(data)}]")
        if data and isinstance(data[0], dict):
            parts.append(f"item0_keys={_key_names(data[0])}")
    else:
        parts.append(f"json={type(data).__name__}")
    return " ".join(parts)


def normalize_display_tag(text: str) -> tuple[str, bool]:
    """대사 맨 앞의 디스플레이 지문 표기만 `[디스플레이: 내용]`으로 맞춘다. 다른 대괄호·대사는 그대로 둔다."""
    match = _DISPLAY_VARIANT.match(text)
    if not match:
        return text, False
    canonical = f"[디스플레이: {match.group(1).strip()}]"
    if match.group(0) == canonical:
        return text, False
    return canonical + text[match.end():], True


def story_response_schema(project: StoryProjectDef) -> dict:
    """Gemini `responseJsonSchema`용 출력 형태. 문장 수 등 값 규칙은 파서·응답 제어가 계속 검사한다."""
    return {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "minItems": 1,
                "maxItems": project.max_lines,
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string", "enum": list(project.speakers)},
                        "text": {"type": "string"},
                    },
                    "required": ["speaker", "text"],
                },
            },
            "reaction": {"type": "string"},
            "intent_id": {"type": "string"},
        },
        "required": ["lines"],
    }


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
            text, normalized = normalize_display_tag(text)
            if normalized:
                logger.info("스토리 지문 표기 정규화: project=%s count=1", project.id)
            # 디스플레이 지문은 한 턴에 최대 1개 (첫 번째만 유지)
            first = _DISPLAY.search(text)
            if first:
                text = (first.group(0) + "\n" + _DISPLAY.sub("", text).strip()).strip()
        if text:
            lines.append(ReplyLine(speaker, text[:MAX_REPLY_CHARS]))
    if not lines:
        raise ValueError("유효한 대사 없음")
    reaction = " ".join(str(data.get("reaction", "")).split())[:MAX_REACTION_CHARS] or DEFAULT_REACTION
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


def story_failure_reason(exc: Exception) -> str:
    """로그용 원인 분류만 추출한다(오류 본문·사용자 입력·키는 남기지 않는다)."""
    if isinstance(exc, GeminiHTTPError):
        return f"provider_http_{exc.status_code}"
    if isinstance(exc, GeminiQuotaError):
        return f"provider_quota_{re.sub(r'[^a-z_]', '', exc.kind)[:20]}"
    if isinstance(exc, GeminiTimeoutError):
        return "provider_timeout"
    message = str(exc)
    if "검증 실패" in message:
        return "response_control:" + re.sub(r"[^a-z_,]", "", message.split(":", 1)[-1])[:80]
    if "연결 실패" in message:
        return "provider_connection"
    if "형식" in message:
        return "provider_response_format"
    return "provider_other"


_DISPLAY_TAG = re.compile(r"\[디스플레이: [^\]]+\]")


def _choice_fallback(project: StoryProjectDef, scene: Scene, choice: SceneChoice) -> list[ReplyLine] | None:
    """선택지의 반응 예시를 고정 대사로 쓴다. 반응 예시에 대사가 없으면 None."""
    from app.services.story_scene_sets import MOCK_FREE_REPLY

    text = choice.reference_reply.strip()
    if not text or text == MOCK_FREE_REPLY:
        return None
    speaker = next((s for s in project.speakers if text.startswith(f"{s}: ")), None)
    if speaker is not None:
        text = text[len(speaker) + 2 :]
    # 시나리오 장면 카드의 반응 방향은 '비비가 "…"'처럼 따옴표 앞에 말하는 대원이 있다. 가장 가까운 이름을 화자로 쓴다.
    head = choice.direction.split('"', 1)[0] if '"' in choice.direction else ""
    if speaker is None and head:
        found = [(head.rfind(name), name) for name in project.speakers if name in head]
        speaker = max(found)[1] if found else None
        if project.id == "fridge":
            display = _DISPLAY_TAG.search(head)
            if display:
                text = f"{display.group(0)}\n{text}"
    return [ReplyLine(speaker or scene.opening_speaker or project.speakers[0], text)]


def _free_fallback(project: StoryProjectDef, scene: Scene, turn: int) -> list[ReplyLine] | None:
    """자유 입력용 장면 고정 대사. scenario_draft_v1은 story_fallback_lines의 초안, 그 밖의 세트는 장면의 기본 응답."""
    from app.services.story_scene_sets import MOCK_FREE_REPLY, SCENARIO_SET

    if project.scene_set == SCENARIO_SET:
        rows = FREE_INPUT_FALLBACK.get(project.id, {}).get(turn + 1, ())
        lines = [ReplyLine(speaker or project.speakers[0], text) for speaker, text in rows]
        return lines or None
    text = scene.default_reply
    if not text or text == MOCK_FREE_REPLY:
        return None
    speaker = next((s for s in project.speakers if text.startswith(f"{s}: ")), scene.opening_speaker)
    if text.startswith(f"{speaker}: "):
        text = text[len(speaker) + 2 :]
    return [ReplyLine(speaker, text)]


def fallback_reply(
    project: StoryProjectDef, scene: Scene, turn: int, choice: SceneChoice | None, nickname: str
) -> tuple[list[ReplyLine], str] | None:
    """AI 실패 시 쓸 고정 대사와 반응. 쓸 대사가 없으면 None(기존처럼 오류 응답)."""
    lines = (_choice_fallback(project, scene, choice) if choice else None) or _free_fallback(project, scene, turn)
    if not lines:
        return None
    filled = [ReplyLine(line.speaker, _fill_nickname(line.text, nickname)) for line in lines]
    return filled, (choice.reaction if choice and choice.reaction else DEFAULT_REACTION)


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
        dialogue=info_from_extra(message.extra if message else None, record.provider),
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
    return fill_user(text, nickname)


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
    fallback_reason: str | None = None  # AI 실패로 고정 대사를 쓴 경우의 사유 코드(로그·extra 전용)


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
    # 스키마를 받는 공급자(Gemini)에만 전달한다. 다른 공급자·테스트 대역의 호출 형태는 그대로다.
    schema_kwargs = (
        {"json_schema": story_response_schema(project)}
        if settings.story_response_schema and getattr(llm, "supports_json_schema", False)
        else {}
    )
    for attempt in range(1, min(settings.story_generation_attempts, MAX_ATTEMPTS) + 1):
        messages, versions = build_story_messages(project, nickname, turn, history, user_text, choice, correction)
        result = await llm.generate(
            messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            json_mode=True,
            **schema_kwargs,
        )
        try:
            lines, reaction = parse_story_output(project, result.text)
        except ValueError as exc:
            logger.warning(
                "스토리 응답 형식 오류: project=%s provider=%s attempt=%d reason=%s %s",
                project.id, result.provider, attempt, exc, describe_output_shape(result.text),
            )
            correction = "JSON 형식이 아니었다. 출력 형식의 JSON 객체 하나만 출력한다."
            seen.append("format")
            continue
        violations = validate_lines(project, turn, [(l.speaker, l.text) for l in lines], previous_replies, nickname)
        if not violations:
            latency = int((time.perf_counter() - started) * 1000)
            return GeneratedReply(lines, reaction, result.provider, result.model, latency, parse_intent(result.text, scene), attempt, seen, versions)
        seen += [v.code for v in violations]
        # 원문·위반 상세(detail)는 남기지 않고 코드와 줄별 문장 수만 기록한다.
        logger.warning(
            "스토리 응답 제어 위반: project=%s turn=%d attempt=%d codes=%s sentences=%s",
            project.id, turn, attempt, ",".join(v.code for v in violations),
            ",".join(str(len(sentences(l.text))) for l in lines),
        )
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
    dialogue: DialogueInfo | None = None,
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
        dialogue=dialogue or DialogueInfo(story_provider=provider, dialogue_provider=provider),
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
    expected_provider: str | None = None,
) -> StoryTurnOutcome | StorySafetyOutcome:
    project = await resolve_project(db, conversation)
    replay = await _check_turn(db, conversation, project, request_id, turn)
    if replay is not None:
        return replay
    # 위기 신호(자유 입력만): LLM 호출·저장·장면 진행 없이 안내 신호와 곁말만 돌려준다. 입력 원문은 기록하지 않는다.
    if choice_id is None and is_story_crisis(text):
        logger.warning("스토리 위기 신호 안내: project=%s turn=%d", project.id, turn)
        speaker, line = COMPANION_LINES.get(project.id, (project.speakers[0], ""))
        return StorySafetyOutcome(
            conversation=conversation,
            project=project,
            request_id=request_id,
            turn=turn,
            lines=[ReplyLine(speaker, line)] if line else [],
            completed_turns=await count_completed(db, conversation.id),
        )
    if expected_provider and get_llm().name != expected_provider:
        raise StoryTurnError(503, "요청한 스토리 공급자를 사용할 수 없습니다.")
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
    if choice is not None:
        # 원문 정확 일치 검증을 통과한 선택지만 서버 기준 호칭으로 채운다(LLM 입력·저장 대화 공통).
        # 자유 입력은 사용자가 쓴 그대로 둔다.
        user_text = _fill_nickname(user_text, nickname)
    history, previous = await _history(db, conversation.id)

    # LLM 호출 동안 DB 트랜잭션(SQLite 잠금)을 잡고 있지 않는다.
    await db.commit()
    started = time.perf_counter()
    try:
        generated = await _generate(project, turn, nickname, history, user_text, choice, previous)
    except LLMError as exc:
        # AI 실패: 오류 화면 대신 장면 고정 대사로 이어 간다. 사유 코드만 기록하고 대사·입력·키는 남기지 않는다.
        reason = story_failure_reason(exc)
        fallback = fallback_reply(project, scene, turn, choice, nickname)
        if fallback is None:
            raise
        logger.warning(
            "스토리 AI 실패, 고정 대사로 진행: project=%s turn=%d conversation=%s input=%s type=%s reason=%s",
            project.id, turn, conversation.id, "choice" if choice else "free", type(exc).__name__, reason,
        )
        generated = GeneratedReply(
            fallback[0], fallback[1], FALLBACK_PROVIDER, FALLBACK_MODEL,
            int((time.perf_counter() - started) * 1000), None, 0, [], {}, reason,
        )
    lines, guardrail_triggered = apply_story_guardrail(project, generated.lines)
    dialogue = DialogueInfo(story_provider=generated.provider, dialogue_provider=generated.provider)
    if not guardrail_triggered:
        # 냉장고 전용·선택 기능(기본 꺼짐): 대사 본문만 Qwen으로 다시 쓴다. 실패하면 Gemini 원본을 그대로 쓴다.
        rewrite = await rewrite_fridge_dialogue(
            project,
            turn,
            story_provider=generated.provider,
            lines=lines,
            reaction=generated.reaction,
            nickname=nickname,
            user_text=user_text,
            from_choice=choice is not None,
            previous_replies=previous,
            conversation_id=conversation.id,
        )
        dialogue = rewrite.info
        if rewrite.text is not None:
            lines = [ReplyLine(lines[0].speaker, rewrite.text)]
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
            "dialogue": dialogue.as_extra(),
            **({"story_fallback": {"reason": generated.fallback_reason}} if generated.fallback_reason else {}),
        },
        guardrail_triggered=guardrail_triggered,
        dialogue=dialogue,
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
    fixed = scene.fixed_lines
    if project.id == "fridge":
        # 냉장고 10턴은 지금까지의 판정 결과(관계 단계)에 맞는 마무리 대사를 쓴다. 대화 중에는 단계를 바꾸지 않는다.
        ending = await judge_conversation(db, conversation, project.id, project.scene_set)
        staged = fridge_trailer_text(ending)
        if staged and fixed:
            fixed = (replace(fixed[0], text=staged),) + fixed[1:]
    lines = fixed_reply_lines(project, fixed, nickname)
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
