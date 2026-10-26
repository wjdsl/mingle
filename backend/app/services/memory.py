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
