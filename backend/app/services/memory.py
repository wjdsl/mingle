"""User Note (장기 기억) 추출·저장·압축.

기본은 규칙 기반 추출로 동작하고, MEMORY_LLM_ENABLED=true 이면 LLM 추출을
추가로 수행한다. 규칙 기반만으로도 이름/취향/생일/최근 사건 등 핵심 정보를
안정적으로 저장할 수 있어 테스트와 시연에 유리하다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import UserNote
from app.services.llm import LLMError, get_llm

logger = logging.getLogger(__name__)

_STOPWORDS = {"너", "나", "저", "그거", "이거", "저거", "것", "거", "너를", "나는"}

_NAME_PATTERNS = [
    re.compile(r"(?:내|제)\s*이름은\s*([가-힣A-Za-z]{2,10})"),
    re.compile(r"(?:나는|저는|내가)\s*([가-힣A-Za-z]{2,10})\s*(?:이야|야|이에요|예요|입니다|라고\s*해)"),
    re.compile(r"(?:나를|저를|날|절)\s*([가-힣A-Za-z]{2,10})\s*(?:라고|이라고)\s*불러"),
]
_BIRTHDAY_PATTERN = re.compile(
    r"생일(?:은|이)?\s*([0-9]{1,2}\s*월\s*[0-9]{1,2}\s*일|[0-9]{1,2}/[0-9]{1,2})"
)
_LIKE_PATTERNS = [
    re.compile(r"([가-힣A-Za-z0-9 ]{2,20}?)(?:을|를)\s*(?:좋아해|좋아합니다|좋아|사랑해|즐겨)"),
    re.compile(r"([가-힣A-Za-z0-9 ]{2,20}?)\s*(?:좋아해|좋아합니다|즐겨)"),
]
_DISLIKE_PATTERNS = [
    re.compile(r"([가-힣A-Za-z0-9 ]{2,20}?)(?:을|를)?\s*(?:싫어해|싫어합니다|싫어|못\s*먹어)"),
]
_EVENT_PATTERN = re.compile(
    r"(?:오늘|어제|지난주|최근에?)\s*(.{2,40}?)(?:했어|했어요|갔어|갔어요|봤어|봤어요|먹었어|먹었어요)"
)


@dataclass(slots=True)
class ExtractedNote:
    key: str
    value: str
    category: str = "profile"
    importance: float = 0.6
    confidence: float = 0.7
    source: str = "rule"


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .,!?'\"")
    return value[:200]


def _normalize_name(value: str) -> str:
    """'지우야' / '지우아' 처럼 호격 조사가 붙은 이름을 정리한다."""
    cleaned = _clean(value)
    if len(cleaned) >= 3 and cleaned[-1] in ("야", "아"):
        cleaned = cleaned[:-1]
    return cleaned


def extract_rule_based(text: str) -> list[ExtractedNote]:
    if not text:
        return []
    results: list[ExtractedNote] = []
    seen: set[str] = set()

    def add(key: str, value: str, category: str, importance: float, confidence: float) -> None:
        value = _clean(value)
        if not value or key in seen:
            return
        if value in _STOPWORDS:
            return
        seen.add(key)
        results.append(
            ExtractedNote(
                key=key,
                value=value,
                category=category,
                importance=importance,
                confidence=confidence,
            )
        )

    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            add("이름", _normalize_name(match.group(1)), "profile", 0.95, 0.9)
            break

    birthday = _BIRTHDAY_PATTERN.search(text)
    if birthday:
        add("생일", birthday.group(1), "profile", 0.85, 0.85)

    for pattern in _LIKE_PATTERNS:
        for match in pattern.finditer(text):
            candidate = _clean(match.group(1))
            candidate = re.sub(r"^(나는|저는|내가|제가)\s*", "", candidate)
            if len(candidate) >= 2 and candidate not in _STOPWORDS:
                add(f"선호_{candidate[:20]}", candidate, "preference", 0.7, 0.75)

    for pattern in _DISLIKE_PATTERNS:
        for match in pattern.finditer(text):
            candidate = _clean(match.group(1))
            if len(candidate) >= 2 and candidate not in _STOPWORDS:
                add(f"비선호_{candidate[:20]}", candidate, "preference", 0.65, 0.7)

    event = _EVENT_PATTERN.search(text)
    if event:
        add("최근_사건", event.group(1), "event", 0.55, 0.6)

    return results


async def extract_with_llm(text: str, persona_name: str) -> list[ExtractedNote]:
    prompt = (
        "다음 사용자 발화에서 장기 기억으로 저장할 정보를 추출하세요.\n"
        "반드시 JSON만 출력: {\"notes\": [{\"key\": \"이름|선호_취미|최근_사건 등\", "
        "\"value\": \"값\", \"category\": \"profile|preference|event|relationship\", "
        "\"importance\": 0.0~1.0}]}\n"
        "저장할 정보가 없으면 {\"notes\": []} 를 출력하세요.\n\n"
        f"페르소나: {persona_name}\n사용자 발화: {text}"
    )
    try:
        result = await get_llm().generate(
            [{"role": "system", "content": "너는 정보 추출기다. JSON만 출력한다."},
             {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
            json_mode=True,
        )
        data = json.loads(result.text)
    except (LLMError, json.JSONDecodeError) as exc:
        logger.warning("LLM 기억 추출 실패: %s", exc)
        return []

    notes: list[ExtractedNote] = []
    for item in data.get("notes", [])[:8]:
        key = _clean(str(item.get("key", "")))
        value = _clean(str(item.get("value", "")))
        if not key or not value:
            continue
        category = str(item.get("category", "profile"))
        if category not in {"profile", "preference", "event", "relationship"}:
            category = "profile"
        try:
            importance = float(item.get("importance", 0.6))
        except (TypeError, ValueError):
            importance = 0.6
        notes.append(
            ExtractedNote(
                key=key,
                value=value,
                category=category,
                importance=max(0.0, min(1.0, importance)),
                confidence=0.8,
                source="llm",
            )
        )
    return notes


async def update_notes(
    db: AsyncSession,
    session_id: str,
    persona_id: str,
    text: str,
    *,
    use_llm: bool | None = None,
) -> list[UserNote]:
    if not settings.memory_extraction_enabled:
        return []

    extracted = extract_rule_based(text)
    if use_llm is None:
        use_llm = settings.memory_llm_enabled
    if use_llm:
        extracted.extend(await extract_with_llm(text, persona_id))
    if not extracted:
        return []

    existing_rows = (
        await db.execute(
            select(UserNote).where(
                UserNote.session_id == session_id,
                UserNote.persona_id == persona_id,
            )
        )
    ).scalars().all()
    existing = {row.key: row for row in existing_rows}

    touched: list[UserNote] = []
    touched_ids: set[str] = set()
    for item in extracted:
        row = existing.get(item.key)
        if row is None:
            row = UserNote(
                session_id=session_id,
                persona_id=persona_id,
                key=item.key,
                value=item.value,
                category=item.category,
                importance=item.importance,
                confidence=item.confidence,
                source=item.source,
            )
            db.add(row)
            existing[item.key] = row
        else:
            row.value = item.value
            row.category = item.category
            row.importance = max(row.importance, item.importance)
            row.confidence = max(row.confidence, item.confidence)
            row.source = item.source
        touched.append(row)

    await db.flush()
    touched_ids = {row.id for row in touched if row.id}
    await _compact_notes(db, session_id, persona_id, keep_ids=touched_ids)
    return touched


async def _compact_notes(
    db: AsyncSession, session_id: str, persona_id: str, keep_ids: set[str]
) -> None:
    """노트가 임계치를 넘으면 중요도가 낮은 노트를 하나의 요약 노트로 합친다."""
    rows = (
        await db.execute(
            select(UserNote).where(
                UserNote.session_id == session_id,
                UserNote.persona_id == persona_id,
            )
        )
    ).scalars().all()
    if len(rows) <= settings.memory_compaction_threshold:
        return

    ordered = sorted(rows, key=lambda row: (row.importance, row.updated_at), reverse=True)
    survivors = ordered[: settings.memory_compaction_threshold - 1]
    survivors_ids = {row.id for row in survivors} | keep_ids
    extras = [row for row in rows if row.id not in survivors_ids]
    if not extras:
        return

    summary = "; ".join(f"{row.key}: {row.value}" for row in extras)[:900]
    merged = next((row for row in rows if row.key == "기타_기억"), None)
    if merged is None:
        merged = UserNote(
            session_id=session_id,
            persona_id=persona_id,
            key="기타_기억",
            value=summary,
            category="event",
            importance=0.3,
            confidence=0.6,
            source="rule",
        )
        db.add(merged)
    else:
        merged.value = f"{merged.value}; {summary}"[:900]
        merged.importance = max(merged.importance, 0.3)

    for row in extras:
        await db.delete(row)
    await db.flush()


async def load_notes(
    db: AsyncSession,
    session_id: str,
    persona_id: str | None,
    *,
    limit: int = 30,
    include_global: bool = True,
) -> list[UserNote]:
    stmt = select(UserNote).where(UserNote.session_id == session_id)
    if persona_id:
        if include_global:
            stmt = stmt.where(
                (UserNote.persona_id == persona_id) | (UserNote.persona_id.is_(None))
            )
        else:
            stmt = stmt.where(UserNote.persona_id == persona_id)
    stmt = stmt.order_by(UserNote.importance.desc(), UserNote.updated_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------- #
# 푸르마 전용 User Note 정책 (브라우저 로컬 저장용, DB를 쓰지 않는 순수 함수)
#
# 근거: docs/Pruma_Data_Design.md 8장, data/usernote/pruma_usernote_importance.json,
#       docs/AI_LLM_DESIGN.md 7장. 위의 일반 페르소나 기억 함수와 UserNote 스키마는 그대로 둔다.
# - 허용 항목: 호칭/별명, 관심사·취향, 약속/응원, 반복 주제 (구간별 선택은 필드만 정의, 추출 미구현)
# - 위기 입력·개인정보·민감정보·타인 정보로 보이는 입력은 해당 발화 전체에서 기억을 만들지 않는다.
# - 중요도는 high/medium/low, 최대 10개. 넘치면 낮은 중요도·오래된 것부터 삭제하고 합치지 않는다.
# --------------------------------------------------------------------------- #

PURUMA_PERSONA_SLUG = "puruma"
PURUMA_MAX_NOTES = 10
PURUMA_VALUE_MAX_CHARS = 40

PURUMA_FIELDS = ("nickname", "interest", "promise", "repeated_topic", "section_choice")
PURUMA_EXTRACTED_FIELDS = ("nickname", "interest", "promise", "repeated_topic")
IMPORTANCE_RANK = {"high": 3, "medium": 2, "low": 1}

# 위기 신호: 기억 추출·저장과 (API 연결 후) 회상을 모두 건너뛴다.
PURUMA_CRISIS_PATTERNS = (
    "자살", "죽고 싶", "죽어버리", "죽을래", "자해", "사라지고 싶", "살기 싫", "살고 싶지 않",
)
# 개인정보·민감정보 신호: 중요도 판정 전에 제외한다(강한 기억 요청이 있어도 저장하지 않음).
_PII_PATTERNS = (
    re.compile(r"(?<!\d)(?:\+?82[- ]?)?0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}(?!\d)"),  # 전화번호
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # 이메일
    re.compile(r"\d{6,}"),  # 학번·계좌 등 긴 숫자
    re.compile(r"\d{2,4}[XxＸ*]{2,}"),  # 일부 가린 학번 (예: 20XXXXXX)
)
_SENSITIVE_KEYWORDS = re.compile(
    r"학번|주민|실명|본명|(?:내|제)\s*이름|이름(?:은|이)\s|연락처|전화|번호|이메일|메일\s?주소|주소|사는\s?곳|집\s?위치|"
    r"생일|생년월일|나이|"
    r"건강|병원|질병|병명|진단|아파서|아픈\s|약을|약\s?먹|우울|공황|불안장애|장애|수술|임신|"
    r"정치|정당|대통령|선거|투표|종교|교회|성당|불교|기독|천주|이슬람|"
    r"성적\s?지향|성\s?정체성"
)
# 타인 정보로 보이는 입력(판정이 어려우면 저장하지 않는다).
_OTHER_PERSON = re.compile(
    r"엄마|아빠|부모|동생|오빠|언니|누나|남자\s?친구|여자\s?친구|남친|여친|친구|룸메|교수님|선생님|"
    r"[가-힣]{2,3}\s?씨(?:가|는|랑|한테|에게|도|의)?(?![가-힣])|"
    r"(?:한|했|하)대(?:요)?(?:$|[\s.!?])|한다더라|한다고\s?했"  # 남의 이야기를 전하는 말
)

_LEADING_NOISE = re.compile(
    r"^(?:(?:나는|난|나|저는|전|내가|제가|나도|요즘|원래|정말|진짜|그냥|앞으로|계속|오늘은|오늘만은|오늘만|지금은|지금|이번에는|그리고|근데)\s*)+"
)
_TRAILING_PARTICLE = re.compile(r"\s*(?:을|를|은|는|이|가|에|에는|도|쪽을|쪽|이랑|랑)$")
_PERSISTENT = re.compile(r"원래|앞으로|계속|자주|항상|늘\s|매일|기억해")
_TRANSIENT = re.compile(r"오늘은|오늘만|지금은|지금\s|이번만|잠깐")

_NICKNAME_PATTERNS = (
    re.compile(r"(?:나를|날|저를|절)\s*([가-힣A-Za-z0-9]{1,10}?)(?:이)?(?:라고|로)\s*불러"),
    re.compile(r"(?:내|제)\s*별명은\s*([가-힣A-Za-z0-9]{1,10}?)(?:이)?(?:야|예요|에요|입니다|이라고|라고)"),
)
_PROMISE_FUTURE = re.compile(r"꼭|다음에|나중에|끝나면|앞으로|계속|언제든|까지")
_PROMISE_VERB = re.compile(r"(?:하|가|보)자|할게|줄게|갈게|도와줄게|응원해\s?줄게")
_CHEER = re.compile(r"힘내|화이팅|파이팅|잘할\s?수\s?있어|할\s?수\s?있어|응원할게|응원해")
_REPEAT_MARKER = re.compile(r"(?:^|\s)(?:또|아까도|다시)(?:\s|$)|또\s?했|아까도")
_REPEAT_TOPIC = re.compile(r"([가-힣A-Za-z0-9]{1,10})\s*(?:얘기|이야기)")
_INTEREST_PATTERNS = (
    # (패턴, 순간 선호 여부). 대상 뒤의 "걸/거/것을"은 _topic에서 떼어 관형형("보는")을 보존한다.
    (re.compile(r"(.{1,24}?)\s*(?:정말|진짜|제일|너무|많이)?\s*좋아(?:해|합니다|요|$|\s)"), False),
    (re.compile(r"(.{1,24}?)\s*(?:정말|진짜|제일|너무)?\s*좋(?:더라|아)"), False),
    (re.compile(r"(.{1,24}?)(?:에|에는)\s*(?:조금|좀|많이)?\s*관심(?:이)?\s*(?:있|생겼|생기)"), False),
    (re.compile(r"(.{1,24}?)(?:이|가)\s*(?:조금|좀|많이)?\s*궁금"), False),
    (re.compile(r"(.{1,24}?)\s*(?:을|를|쪽을)\s*(?:계속|더)?\s*알아보고\s*싶"), False),
    (re.compile(r"(.{1,24}?(?:\s(?:걸|거|것을))?)\s*(?:을|를)?\s*자주"), False),
    (re.compile(r"(.{1,24}?(?:\s(?:게|거))?)\s*(?:은|는|이|가)?\s*(?:제일|정말|진짜|너무)?\s*재밌"), False),
    (re.compile(r"(.{1,20}?)(?:이|가|을|를)\s*먹고\s*싶"), True),
)
# 관심사 대상이 될 수 없는 말(대화 상대·관계 표현 등). 포함되면 저장하지 않는다.
_NOT_A_TOPIC = re.compile(r"(?:^|\s)(?:너|너를|널|당신|푸르마|선배|그거|이거|저거|그것|이것)(?:$|\s)")


@dataclass(slots=True)
class PurumaNote:
    """브라우저 로컬에 저장할 푸르마 기억 1건 (팀 설계의 key/value/importance/created_at_turn 대응)."""

    key: str
    field: str
    value: str
    importance: str = "medium"
    created_at_turn: int = 0
    updated_at_turn: int = 0


def is_crisis_text(text: str) -> bool:
    return any(pattern in (text or "") for pattern in PURUMA_CRISIS_PATTERNS)


def is_sensitive_text(text: str) -> bool:
    """개인정보·민감정보·타인 정보로 보이면 True (애매하면 저장하지 않는 쪽)."""
    value = text or ""
    if any(pattern.search(value) for pattern in _PII_PATTERNS):
        return True
    return bool(_SENSITIVE_KEYWORDS.search(value) or _OTHER_PERSON.search(value))


def memory_skip_reason(text: str) -> str | None:
    """기억 처리를 건너뛸 사유 코드("crisis" | "sensitive"). 원문은 반환·기록하지 않는다."""
    if is_crisis_text(text):
        return "crisis"
    if is_sensitive_text(text):
        return "sensitive"
    return None


def _topic(raw: str) -> str:
    value = _clean(raw)
    value = _LEADING_NOISE.sub("", value)
    value = re.sub(r"^.*?보다\s+", "", value)  # "밥보다 빵" → "빵"
    modifier = re.search(r"\s(?:걸|거|게|것을|것)$", value)
    if modifier:
        # "그림 보는 걸" → "그림 보는" (관형형 '는'을 조사로 떼지 않는다)
        return value[: modifier.start()].strip()[:PURUMA_VALUE_MAX_CHARS]
    previous = None
    while previous != value:
        previous = value
        value = _TRAILING_PARTICLE.sub("", value).strip()
    return value[:PURUMA_VALUE_MAX_CHARS]


def _display(topic: str) -> str:
    # "그림 보는" 처럼 관형형으로 끝나면 "그림 보는 것"으로 읽기 쉽게 만든다.
    return f"{topic} 것" if re.search(r"[는던]$", topic) else topic


def normalize_puruma_key(field: str, topic: str) -> str:
    compact = re.sub(r"[\s\W_]+", "", topic or "")
    return f"{field}:{compact}" if field != "nickname" else "nickname"


def _note(field: str, topic: str, importance: str, turn: int, value: str | None = None) -> PurumaNote | None:
    shown = _clean(value if value is not None else _display(topic))[:PURUMA_VALUE_MAX_CHARS]
    if not topic or not shown or len(re.sub(r"[^가-힣A-Za-z0-9]", "", topic)) < 1:
        return None
    if topic in _STOPWORDS or _NOT_A_TOPIC.search(f" {topic} ") or is_sensitive_text(shown):
        return None
    return PurumaNote(normalize_puruma_key(field, topic), field, shown, importance, turn, turn)


def extract_puruma_notes(text: str, turn: int = 0) -> list[PurumaNote]:
    """사용자 발화 1개에서 허용 항목만 규칙으로 추출한다. 위기·민감 입력은 빈 목록."""
    if not text or memory_skip_reason(text):
        return []
    sentence = _clean(text)
    notes: list[PurumaNote] = []

    for pattern in _NICKNAME_PATTERNS:
        match = pattern.search(sentence)
        if match:
            nickname = match.group(1)
            if not nickname.isdigit():
                note = _note("nickname", nickname, "high", turn, value=nickname)
                if note:
                    notes.append(note)
            break

    if _PROMISE_VERB.search(sentence) and _PROMISE_FUTURE.search(sentence):
        note = _note("promise", sentence, "high", turn, value=sentence)
        if note:
            notes.append(note)
    elif _CHEER.search(sentence):
        note = _note("promise", sentence, "medium", turn, value=sentence)
        if note:
            notes.append(note)

    if _REPEAT_MARKER.search(sentence):
        topic_match = _REPEAT_TOPIC.search(sentence)
        if topic_match:
            topic = _topic(topic_match.group(1))
        else:
            # "아까도 말했지만 …"처럼 주제어가 없으면 뒷부분을 주제로 쓴다.
            topic = _topic(re.split(r"말했지만|말했는데|했지만", sentence, maxsplit=1)[-1])
        note = _note("repeated_topic", topic, "high", turn)
        if note:
            notes.append(note)

    persistent = bool(_PERSISTENT.search(sentence))
    transient = bool(_TRANSIENT.search(sentence))
    for clause in re.split(r"[.!?,]\s*|\s(?:그리고|근데)\s|(?:인데|지만|는데)\s", sentence):
        for pattern, momentary in _INTEREST_PATTERNS:
            match = pattern.search(clause)
            if not match:
                continue
            topic = _topic(match.group(1))
            if not topic:
                continue
            if momentary or transient:
                importance = "low"
            elif persistent:
                importance = "high"
            else:
                importance = "medium"
            note = _note("interest", topic, importance, turn)
            if note:
                notes.append(note)
            break

    unique: dict[str, PurumaNote] = {}
    for note in notes:
        current = unique.get(note.key)
        if current is None or IMPORTANCE_RANK[note.importance] > IMPORTANCE_RANK[current.importance]:
            unique[note.key] = note
    return list(unique.values())


def sanitize_puruma_notes(notes: list[PurumaNote]) -> list[PurumaNote]:
    """외부(브라우저)에서 받은 기억을 다시 검증한다. 허용되지 않은 항목은 버린다."""
    clean: list[PurumaNote] = []
    for note in notes:
        if note.field not in PURUMA_FIELDS or note.importance not in IMPORTANCE_RANK:
            continue
        value = _clean(note.value)[:PURUMA_VALUE_MAX_CHARS]
        if not value or is_crisis_text(value) or is_sensitive_text(value):
            continue
        clean.append(PurumaNote(note.key[:120], note.field, value, note.importance, note.created_at_turn, note.updated_at_turn))
    return clean


def _sort_key(note: PurumaNote) -> tuple[int, int, int]:
    return (IMPORTANCE_RANK[note.importance], note.updated_at_turn, note.created_at_turn)


def merge_puruma_notes(
    existing: list[PurumaNote], incoming: list[PurumaNote], *, limit: int = PURUMA_MAX_NOTES
) -> list[PurumaNote]:
    """같은 key는 갱신하고, 같은 관심사가 다시 나오면 high로 올린다. 상한을 넘으면 낮은 순으로 삭제(합치지 않음)."""
    merged: dict[str, PurumaNote] = {note.key: note for note in sanitize_puruma_notes(existing)}
    for note in sanitize_puruma_notes(incoming):
        current = merged.get(note.key)
        if current is None:
            merged[note.key] = note
            continue
        rank = max(IMPORTANCE_RANK[current.importance], IMPORTANCE_RANK[note.importance])
        if note.field in ("interest", "repeated_topic") and rank >= IMPORTANCE_RANK["medium"]:
            rank = IMPORTANCE_RANK["high"]  # 같은 허용 관심사·주제가 2회 이상 → high
        importance = next(name for name, value in IMPORTANCE_RANK.items() if value == rank)
        merged[note.key] = PurumaNote(
            note.key, note.field, note.value, importance, current.created_at_turn, note.updated_at_turn
        )
    ordered = sorted(merged.values(), key=_sort_key, reverse=True)
    return ordered[:limit]


def puruma_notes_for_prompt(
    notes: list[PurumaNote], user_text: str, *, limit: int = PURUMA_MAX_NOTES
) -> list[PurumaNote]:
    """응답 맥락에 넣을 기억. 위기 입력이면 회상하지 않도록 빈 목록을 돌려준다."""
    if is_crisis_text(user_text):
        return []
    return sorted(sanitize_puruma_notes(notes), key=_sort_key, reverse=True)[:limit]


def update_puruma_notes(existing: list[PurumaNote], user_text: str, turn: int) -> list[PurumaNote]:
    """한 턴의 기억 갱신. 위기·민감 입력이면 새 기억 없이 기존 목록(재검증 후)만 돌려준다."""
    return merge_puruma_notes(existing, extract_puruma_notes(user_text, turn))
