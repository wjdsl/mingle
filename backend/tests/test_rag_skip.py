"""지식 문서가 없는 페르소나는 임베딩 호출 없이 검색을 건너뛴다 (Mock/가짜 공급자, 외부 API 없음)."""

from __future__ import annotations

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Persona
from app.services import rag


class CountingLLM:
    name = "mock"

    def __init__(self, vector=None) -> None:
        self.embed_calls: list[list[str]] = []
        self.vector = vector or [1.0] + [0.0] * 1535

    async def embed(self, texts):
        self.embed_calls.append(list(texts))
        return [self.vector for _ in texts]


async def _persona_id(slug: str) -> str:
    async with SessionLocal() as db:
        return (await db.execute(select(Persona.id).where(Persona.slug == slug))).scalar_one()


async def test_persona_without_knowledge_skips_embedding(client, monkeypatch):
    llm = CountingLLM()
    monkeypatch.setattr(rag, "get_llm", lambda: llm)
    persona_id = await _persona_id("puruma")  # RAG 지식 문서 없음
    async with SessionLocal() as db:
        assert await rag.retrieve(db, persona_id, "내가 좋아하는 게 뭐였지?") == []
    assert llm.embed_calls == []


async def test_persona_with_knowledge_still_embeds_and_searches(client, monkeypatch):
    llm = CountingLLM()
    monkeypatch.setattr(rag, "get_llm", lambda: llm)
    persona_id = await _persona_id("momo-dalkom")  # 지식 문서 있음
    async with SessionLocal() as db:
        await rag.retrieve(db, persona_id, "케이크 알려줘", min_score=-1.0)
    assert llm.embed_calls == [["케이크 알려줘"]]  # 기존 동작 유지: 질문 임베딩 1회


async def test_empty_query_still_returns_without_embedding(client, monkeypatch):
    llm = CountingLLM()
    monkeypatch.setattr(rag, "get_llm", lambda: llm)
    persona_id = await _persona_id("momo-dalkom")
    async with SessionLocal() as db:
        assert await rag.retrieve(db, persona_id, "   ") == []
    assert llm.embed_calls == []


async def test_no_documents_is_distinct_from_no_matching_result(client, monkeypatch):
    # 문서가 있는 페르소나에 점수 기준을 넘길 수 없게 해도 임베딩은 수행된다(결과만 비어 있음).
    llm = CountingLLM(vector=[0.0] * 1536)
    monkeypatch.setattr(rag, "get_llm", lambda: llm)
    persona_id = await _persona_id("seo-harin")
    async with SessionLocal() as db:
        assert await rag.retrieve(db, persona_id, "달빛", min_score=2.0) == []
    assert len(llm.embed_calls) == 1


async def test_puruma_chat_turn_makes_no_embedding_call(client, monkeypatch):
    from app.services import chat_service
    from app.services.llm.base import LLMProvider, LLMResult

    class OneShot(LLMProvider):
        name = "mock"
        chat_model = "x"

        def __init__(self) -> None:
            self.embed_calls = 0

        async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
            return LLMResult(text="네, 선배!", provider=self.name, model=self.chat_model, latency_ms=1)

        async def stream(self, messages, *, temperature=None, max_tokens=None):
            yield "네"

        async def embed(self, texts):
            self.embed_calls += 1
            return [[0.0] for _ in texts]

    llm = OneShot()
    monkeypatch.setattr(chat_service, "get_llm", lambda: llm)
    monkeypatch.setattr(rag, "get_llm", lambda: llm)
    created = await client.post("/api/sessions", json={"persona_slug": "puruma"})
    body = created.json()
    response = await client.post(
        "/api/chat",
        headers={"X-Personal-Code": body["personal_code"]},
        json={"conversation_id": body["conversation"]["id"], "message": "안녕", "notes": []},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == []
    assert llm.embed_calls == 0
