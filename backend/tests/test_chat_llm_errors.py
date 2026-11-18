"""/api/chat의 Gemini 오류 구분 테스트 (가짜 공급자, 외부 API 없음)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.db.models import Message
from app.services import chat_service
from app.services.llm import LLMError
from app.services.llm.base import LLMProvider
from app.services.llm.gemini_provider import GeminiHTTPError, GeminiQuotaError, GeminiTimeoutError


class FailingLLM(LLMProvider):
    name = "mock"
    chat_model = "fail"

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
        raise self.error

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        raise self.error
        yield ""  # pragma: no cover

    async def embed(self, texts):
        return [[0.0] for _ in texts]


async def _chat(client, monkeypatch, error, persona="puruma", notes=None):
    monkeypatch.setattr(chat_service, "get_llm", lambda: FailingLLM(error))
    created = await client.post("/api/sessions", json={"persona_slug": persona})
    body = created.json()
    payload = {"conversation_id": body["conversation"]["id"], "message": "안녕"}
    if notes is not None:
        payload["notes"] = notes
    response = await client.post("/api/chat", headers={"X-Personal-Code": body["personal_code"]}, json=payload)
    return response, body["conversation"]["id"]


@pytest.mark.parametrize("kind,retry,expected_header", [("daily", None, None), ("minute", 7, "7"), ("unknown", None, None)])
async def test_quota_error_is_429_with_code_and_retry_after(client, monkeypatch, kind, retry, expected_header):
    response, _ = await _chat(client, monkeypatch, GeminiQuotaError(kind, retry), notes=[])
    assert response.status_code == 429
    assert response.json()["detail"] == {"code": f"gemini_quota_{kind}"}
    assert response.headers.get("retry-after") == expected_header


async def test_timeout_is_504(client, monkeypatch):
    response, _ = await _chat(client, monkeypatch, GeminiTimeoutError("Gemini 응답 시간 초과"), notes=[])
    assert response.status_code == 504
    assert "시간" in response.json()["detail"]


async def test_provider_503_is_503_unavailable(client, monkeypatch):
    response, _ = await _chat(client, monkeypatch, GeminiHTTPError(503), notes=[])
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "gemini_unavailable"}


@pytest.mark.parametrize("error", [GeminiHTTPError(500), GeminiHTTPError(400), LLMError("Gemini 연결 실패")])
async def test_other_llm_errors_stay_502(client, monkeypatch, error):
    response, _ = await _chat(client, monkeypatch, error, notes=[])
    assert response.status_code == 502
    assert "AI 응답 생성에 실패" in response.json()["detail"]


async def test_other_persona_uses_same_mapping_and_failure_saves_nothing(client, monkeypatch):
    response, conversation_id = await _chat(client, monkeypatch, GeminiQuotaError("minute", 3), persona="seo-harin")
    assert response.status_code == 429
    async with SessionLocal() as db:
        roles = (await db.execute(select(Message.role).where(Message.conversation_id == conversation_id))).scalars().all()
        assert roles == ["assistant"]  # 인사말만 있고 실패한 요청의 사용자 메시지는 저장되지 않음
        assert (await db.execute(select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id))).scalar_one() == 1
