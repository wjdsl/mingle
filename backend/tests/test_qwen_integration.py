"""Qwen 공급자 통합 테스트 — 실제 Colab API 없이 httpx.MockTransport로 검증한다."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import Message
from app.services import chat_service, llm as llm_module, rag
from app.services.llm import LLMError, ensure_llm_ready, get_llm, reset_llm
from app.services.llm.qwen_provider import QwenProvider


def _qwen(handler) -> tuple[QwenProvider, list[dict]]:
    provider = QwenProvider(base_url="https://qwen.example.test", api_key="test-secret")
    seen: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    provider._client = httpx.AsyncClient(
        base_url="https://qwen.example.test",
        headers={"Authorization": "Bearer test-secret"},
        transport=httpx.MockTransport(wrapped),
    )
    return provider, seen


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"response": "큐웬의 대답", "model": "Qwen2.5-3B-Instruct-EXP-004"})


def _use(monkeypatch, provider) -> None:
    monkeypatch.setattr(chat_service, "get_llm", lambda: provider)
    monkeypatch.setattr(rag, "get_llm", lambda: provider)


async def _start(client, persona):
    created = (await client.post("/api/sessions", json={"persona_slug": persona})).json()
    headers = {"X-Personal-Code": created["personal_code"]}
    return headers, created["conversation"]["id"]


@pytest.fixture(autouse=True)
def _restore_registry():
    yield
    reset_llm()


async def test_chat_uses_qwen_without_embedding_and_clamps_tokens(client, monkeypatch):
    provider, seen = _qwen(_ok)
    _use(monkeypatch, provider)
    headers, cid = await _start(client, "seo-harin")  # RAG 지식 문서가 있는 페르소나

    response = await client.post("/api/chat", headers=headers, json={"conversation_id": cid, "message": "안녕"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == "큐웬의 대답"
    assert body["provider"] == "qwen"  # Mock 응답이 아니라 Qwen 응답
    assert [r["messages"][-1]["content"] for r in seen] == ["안녕"]  # /generate만 호출(임베딩 없음)
    assert 1 <= seen[0]["max_new_tokens"] <= 300  # LLM_MAX_TOKENS(700)가 상한으로 제한됨
    assert len(seen[0]["messages"]) <= 20
    async with SessionLocal() as db:
        stored = (await db.execute(select(Message.provider).where(Message.conversation_id == cid))).scalars().all()
    assert "qwen" in stored


async def test_stream_endpoint_falls_back_to_single_token(client, monkeypatch):
    provider, _ = _qwen(_ok)
    _use(monkeypatch, provider)
    headers, cid = await _start(client, "seo-harin")

    async with client.stream(
        "POST", "/api/chat/stream", headers=headers, json={"conversation_id": cid, "message": "안녕"}
    ) as response:
        text = "".join([chunk async for chunk in response.aiter_text()])

    assert response.status_code == 200
    assert "event: token" in text and "큐웬의 대답" in text
    assert "event: final" in text and '"provider": "qwen"' in text
    assert "event: error" not in text


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(401, json={"detail": "Unauthorized"}),
        lambda r: httpx.Response(500, text="boom"),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
    ids=["401", "500", "connect", "timeout"],
)
async def test_qwen_failures_follow_existing_502_rule(client, monkeypatch, handler):
    provider, _ = _qwen(handler)
    _use(monkeypatch, provider)
    headers, cid = await _start(client, "seo-harin")

    response = await client.post("/api/chat", headers=headers, json={"conversation_id": cid, "message": "안녕"})

    assert response.status_code == 502
    async with SessionLocal() as db:  # 실패한 턴은 저장되지 않는다(Mock 응답으로 대체되지 않음)
        roles = (await db.execute(select(Message.role).where(Message.conversation_id == cid))).scalars().all()
    assert "user" not in roles


# --- 공급자 선택 ---


def _configure(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    reset_llm()


def test_auto_never_selects_qwen(monkeypatch):
    _configure(monkeypatch, llm_provider="auto", openai_api_key=None, gemini_api_key=None,
               qwen_api_url="https://qwen.example.test", qwen_api_key="k")
    assert settings.resolved_provider == "mock"
    assert get_llm().name == "mock"
    monkeypatch.setattr(settings, "gemini_api_key", "g")
    assert settings.resolved_provider == "gemini"  # 기존 순서 유지


def test_explicit_qwen_selects_qwen(monkeypatch):
    _configure(monkeypatch, llm_provider="qwen", qwen_api_url="https://qwen.example.test", qwen_api_key="k")
    assert get_llm().name == "qwen"
    assert get_llm().chat_model == "Qwen2.5-3B-Instruct-EXP-004"


@pytest.mark.parametrize(
    "url,key,missing",
    [(None, "k", "QWEN_API_URL"), ("https://q.test", None, "QWEN_API_KEY"), (None, None, "QWEN_API_URL")],
)
def test_incomplete_qwen_config_is_an_error_not_mock(monkeypatch, url, key, missing):
    _configure(monkeypatch, llm_provider="qwen", qwen_api_url=url, qwen_api_key=key)
    with pytest.raises(LLMError, match=missing):
        get_llm()


def test_insecure_qwen_url_is_rejected(monkeypatch):
    _configure(monkeypatch, llm_provider="qwen", qwen_api_url="http://example.com", qwen_api_key="k")
    with pytest.raises(LLMError, match="QWEN_API_URL"):
        get_llm()


# --- 시작 시 상태 확인 ---


async def test_ensure_ready_skips_embedding_and_keeps_qwen(monkeypatch):
    provider, seen = _qwen(_ok)
    reset_llm()
    monkeypatch.setattr(llm_module, "_build_provider", lambda: provider)

    await ensure_llm_ready()

    assert get_llm().name == "qwen"
    assert llm_module.is_degraded() is False
    assert len(seen) == 1  # 생성 확인 1회만


async def test_ensure_ready_never_calls_embed_for_qwen(monkeypatch):
    """회귀: Qwen은 임베딩 미지원 플래그가 꺼져 있어야 하고, 준비 검사에서 embed()가 호출되면 안 된다."""
    provider, seen = _qwen(_ok)
    assert provider.supports_embedding is False
    assert provider.supports_streaming is False

    async def _fail_embed(texts):
        raise AssertionError("ensure_llm_ready()가 Qwen embed()를 호출했습니다.")

    monkeypatch.setattr(provider, "embed", _fail_embed)
    reset_llm()
    monkeypatch.setattr(llm_module, "_build_provider", lambda: provider)

    await ensure_llm_ready()

    assert get_llm().name == "qwen"
    assert llm_module.is_degraded() is False
    assert len(seen) == 1


async def test_ensure_ready_failure_is_reported_as_degraded(monkeypatch):
    provider, _ = _qwen(lambda r: httpx.Response(500, text="boom"))
    reset_llm()
    monkeypatch.setattr(llm_module, "_build_provider", lambda: provider)

    await ensure_llm_ready()

    assert llm_module.is_degraded() is True
    assert get_llm().name == "qwen"
    assert "Qwen" in (llm_module.degraded_reason() or "")


# --- 미지원 기능은 명확히 거부 ---


async def test_unsupported_features_stay_explicit():
    provider, _ = _qwen(_ok)
    with pytest.raises(LLMError):
        await provider.generate([{"role": "user", "content": "x"}], json_mode=True)
    with pytest.raises(LLMError):
        await provider.embed(["x"])
    with pytest.raises(LLMError):
        await provider.generate([{"role": "user", "content": "x" * 12001}])
    with pytest.raises(LLMError):
        await provider.generate([{"role": "user", "content": "x"}] * 21)
