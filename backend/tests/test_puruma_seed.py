"""푸르마 페르소나 시드 테스트 (Mock LLM, 외부 API 없음).

- 신규 DB / 기존 3종만 있는 DB / 이미 푸르마가 있는 DB에서 '없을 때만 생성'을 검증한다.
- 개강 장면 지시가 턴 1·2에만 한 번씩 적용되고 턴 3에는 없는지 검증한다.
- 시드 문장이 prompts/pruma_system.md 원문과 어긋나지 않는지 검증한다(원문 파일은 수정하지 않는다).
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401  (메타데이터 등록)
from app.db import seed
from app.db.base import Base, SessionLocal
from app.db.models import (
    CTADef,
    Conversation,
    ConversationEventLog,
    EndingDef,
    MarketingTriggerDef,
    Message,
    Persona,
    PersonaKnowledge,
    RelationshipState,
    StoryEventDef,
    UserNote,
    UserSession,
)
from app.db.seed_puruma import (
    MEMORY_SOURCE,
    OPENING_SOS,
    OPENING_STORY_EVENTS,
    PURUMA_PERSONA,
    SOURCE_SENTENCES,
)
from app.services import chat_service
from app.services.llm.base import LLMProvider, LLMResult

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_SOURCE = REPO_ROOT / "prompts" / "pruma_system.md"
PLANNING_DOC = REPO_ROOT / "docs" / "푸르마_프로젝트_기획서.md"
DEMO_SLUGS = {"seo-harin", "kai-orbital7", "momo-dalkom"}
TURN1_HINT = OPENING_STORY_EVENTS[0]["narrative_hint"]
TURN2_HINT = OPENING_STORY_EVENTS[1]["narrative_hint"]


class CapturingLLM(LLMProvider):
    name = "mock"
    chat_model = "capture"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
        self.prompts.append(messages[0]["content"])
        return LLMResult(text="선배, 고마워요!", provider=self.name, model=self.chat_model, latency_ms=1)

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        self.prompts.append(messages[0]["content"])
        yield "선배, 고마워요!"

    async def embed(self, texts):
        return [[0.0] for _ in texts]


# --------------------------------------------------------------------------- #
# 격리된 DB에서 시드 동작 검증
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def seed_db(monkeypatch, tmp_path):
    """공유 테스트 DB와 분리된 빈 SQLite DB. seed_database가 이 DB를 쓰도록 바꾼다."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'seed.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(seed, "SessionLocal", maker)
    yield maker
    await engine.dispose()


async def _snapshot_demo(maker) -> dict:
    """푸르마가 아닌 페르소나와 그 하위 행의 전체 값."""
    async with maker() as db:
        personas = (await db.execute(select(Persona).where(Persona.slug != "puruma"))).scalars().all()
        ids = [p.id for p in personas]
        columns = [c.key for c in Persona.__table__.columns]
        snapshot = {"personas": sorted(tuple(str(getattr(p, c)) for c in columns) for p in personas)}
        for model in (PersonaKnowledge, StoryEventDef, EndingDef, MarketingTriggerDef):
            rows = (await db.execute(select(model).where(model.persona_id.in_(ids)))).scalars().all()
            cols = [c.key for c in model.__table__.columns if c.key != "embedding"]
            snapshot[model.__tablename__] = sorted(tuple(str(getattr(r, c)) for c in cols) for r in rows)
        ctas = (await db.execute(select(CTADef))).scalars().all()
        snapshot["ctas"] = sorted((c.id, c.trigger_id, c.label, c.url) for c in ctas)
        return snapshot


async def _puruma_counts(maker) -> dict:
    async with maker() as db:
        rows = (await db.execute(select(Persona).where(Persona.slug == "puruma"))).scalars().all()
        result = {"personas": len(rows)}
        if rows:
            pid = rows[0].id
            for model in (PersonaKnowledge, StoryEventDef, EndingDef, MarketingTriggerDef):
                result[model.__tablename__] = (
                    await db.execute(select(func.count()).select_from(model).where(model.persona_id == pid))
                ).scalar_one()
        return result


async def test_fresh_db_creates_demo_personas_and_puruma(seed_db):
    await seed.seed_database()
    async with seed_db() as db:
        slugs = set((await db.execute(select(Persona.slug))).scalars().all())
        puruma = (await db.execute(select(Persona).where(Persona.slug == "puruma"))).scalar_one()
    assert slugs == DEMO_SLUGS | {"puruma"}
    assert puruma.greeting == OPENING_SOS and puruma.is_active
    assert await _puruma_counts(seed_db) == {
        "personas": 1, "persona_knowledge": 0, "story_events": 2, "endings": 0, "marketing_triggers": 0,
    }


async def test_existing_db_without_puruma_gets_puruma_and_keeps_demo_rows(seed_db):
    # 푸르마 도입 전 시드 상태: 데모 3종만 있음
    async with seed_db() as db:
        for data in seed.PERSONAS:
            await seed._create_persona(db, data)
        await db.commit()
    before = await _snapshot_demo(seed_db)
    assert (await _puruma_counts(seed_db))["personas"] == 0

    await seed.seed_database()

    assert (await _puruma_counts(seed_db))["personas"] == 1
    assert (await _puruma_counts(seed_db))["story_events"] == 2
    assert await _snapshot_demo(seed_db) == before  # 기존 3종과 하위 데이터 변경 없음


async def test_existing_puruma_is_not_overwritten_or_duplicated(seed_db):
    await seed.seed_database()
    async with seed_db() as db:
        puruma = (await db.execute(select(Persona).where(Persona.slug == "puruma"))).scalar_one()
        puruma.greeting = "운영자가 바꾼 인사말"
        puruma.system_prompt = "운영자가 바꾼 지침"
        puruma.is_active = False
        await db.execute(
            delete(StoryEventDef).where(
                StoryEventDef.persona_id == puruma.id, StoryEventDef.code == "opening_late_entry"
            )
        )
        await db.commit()
    before = await _snapshot_demo(seed_db)

    await seed.seed_database()
    await seed.seed_database()

    async with seed_db() as db:
        rows = (await db.execute(select(Persona).where(Persona.slug == "puruma"))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].greeting, rows[0].system_prompt, rows[0].is_active) == ("운영자가 바꾼 인사말", "운영자가 바꾼 지침", False)
    assert (await _puruma_counts(seed_db))["story_events"] == 1  # 지운 이벤트를 되살리지 않음
    assert await _snapshot_demo(seed_db) == before


# --------------------------------------------------------------------------- #
# 원문(prompts/pruma_system.md) 일치
# --------------------------------------------------------------------------- #

def _persona_text() -> str:
    fields = ("worldview", "character_sheet", "speech_style", "guardrails", "system_prompt")
    return "\n".join(PURUMA_PERSONA[f] for f in fields)


def test_transcribed_sentences_match_source_prompt():
    source = PROMPT_SOURCE.read_text(encoding="utf-8")
    missing = [s for s in SOURCE_SENTENCES if s not in source]
    assert not missing, f"pruma_system.md 원문과 다른 문장: {missing}"
    text = _persona_text()
    assert all(s in text for s in SOURCE_SENTENCES)


def test_memory_recall_rule_is_kept_not_relaxed():
    prompt = PURUMA_PERSONA["system_prompt"]
    for sentence in MEMORY_SOURCE:
        assert sentence in prompt
    assert "회상 허용 여부를 알 수 없으면 먼저 과거 기억을 꺼내지 않는다." in prompt
    for relaxed in ("자연스럽게 활용", "먼저 꺼내도", "적극적으로 회상"):
        assert relaxed not in prompt


def test_meta_and_integration_notes_are_excluded():
    text = _persona_text()
    for meta in ("미연동 초안", "JSON 스키마", "향후 구성기", "docs/", ".json", "설계 문서", "데이터 담당자", "RAG", "### "):
        assert meta not in text, meta


def test_no_rag_endings_or_promotions_and_sos_matches_planning():
    assert PURUMA_PERSONA["knowledge"] == []
    assert PURUMA_PERSONA["endings"] == [] and PURUMA_PERSONA["triggers"] == []
    assert "개강·축제·기말/종강 구간에는 홍보를 하지 않는다." in PURUMA_PERSONA["system_prompt"]
    assert OPENING_SOS in PLANNING_DOC.read_text(encoding="utf-8")
    for event in OPENING_STORY_EVENTS:
        assert event["effects"] == {}  # 스탯·친밀도·구간을 바꾸지 않음


# --------------------------------------------------------------------------- #
# 개강 2턴 장면 지시 (공유 테스트 DB, /api/chat)
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def puruma_chat(client, monkeypatch):
    llm = CapturingLLM()
    monkeypatch.setattr(chat_service, "get_llm", lambda: llm)
    created = await client.post("/api/sessions", json={"display_name": "선배", "persona_slug": "puruma"})
    assert created.status_code == 201, created.text
    body = created.json()
    ctx = {
        "headers": {"X-Personal-Code": body["personal_code"]},
        "conversation_id": body["conversation"]["id"],
        "session_id": body["session"]["id"],
        "llm": llm,
    }
    yield ctx
    async with SessionLocal() as db:
        cid, sid = ctx["conversation_id"], ctx["session_id"]
        await db.execute(delete(Message).where(Message.conversation_id == cid))
        await db.execute(delete(RelationshipState).where(RelationshipState.conversation_id == cid))
        await db.execute(delete(ConversationEventLog).where(ConversationEventLog.conversation_id == cid))
        await db.execute(delete(UserNote).where(UserNote.session_id == sid))
        await db.execute(delete(Conversation).where(Conversation.id == cid))
        await db.execute(delete(UserSession).where(UserSession.id == sid))
        await db.commit()


async def test_opening_events_apply_on_turn_1_and_2_only(client, puruma_chat):
    messages = await client.get(
        f"/api/conversations/{puruma_chat['conversation_id']}/messages", headers=puruma_chat["headers"]
    )
    assert [m["content"] for m in messages.json()] == [OPENING_SOS]  # 첫 메시지는 고정 SOS

    codes = []
    for text in ("지도 같이 보자", "천천히, 조용히 들어가자", "수업 끝나고 뭐 할까?"):
        response = await client.post(
            "/api/chat",
            headers=puruma_chat["headers"],
            json={"conversation_id": puruma_chat["conversation_id"], "message": text},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        codes.append([event["code"] for event in body["story_events"]])
        assert body["triggers"] == [] and body["ending"] is None
        assert body["state"]["chapter"] == 1

    assert codes == [["opening_find_classroom"], ["opening_late_entry"], []]
    first, second, third = puruma_chat["llm"].prompts
    assert TURN1_HINT in first and TURN2_HINT not in first
    assert TURN2_HINT in second and TURN1_HINT not in second
    assert "## 이번 턴 연출 지침" not in third
    # 실제 시스템 프롬프트에도 원문 회상 규칙이 들어간다.
    assert "회상 허용 여부를 알 수 없으면 먼저 과거 기억을 꺼내지 않는다." in first

    async with SessionLocal() as db:
        logged = (
            await db.execute(
                select(ConversationEventLog.code).where(
                    ConversationEventLog.conversation_id == puruma_chat["conversation_id"],
                    ConversationEventLog.kind == "story",
                )
            )
        ).scalars().all()
    assert sorted(logged) == ["opening_find_classroom", "opening_late_entry"]


def test_response_format_and_no_save_promise_rules_are_present():
    from app.db.seed_puruma import FORMAT_ADAPTED, MEMORY_ADAPTED, SPEECH_SOURCE

    prompt = PURUMA_PERSONA["system_prompt"]
    assert SPEECH_SOURCE[1] == "한 번의 응답은 가급적 두세 문장으로 간결하게 한다."
    assert prompt.rstrip().splitlines()[-1].startswith("[응답 형식]")  # 공통 규칙보다 뒤에 읽히도록 마지막 줄
    for sentence in (SPEECH_SOURCE[1], *FORMAT_ADAPTED):
        assert sentence in prompt.splitlines()[-1]
    save_rule = next(s for s in MEMORY_ADAPTED if "저장 약속" in s)
    assert save_rule in prompt
    # 원문의 '저장을 완료했다고 말하지 않는다'와 모순되지 않고, 회상 규칙은 그대로다.
    assert "저장을 완료했다고 말하지 않는다." in prompt
    assert "회상 허용 여부를 알 수 없으면 먼저 과거 기억을 꺼내지 않는다." in prompt
