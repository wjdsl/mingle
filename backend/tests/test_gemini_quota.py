"""Gemini 전송·할당량 계약을 외부 요청 없이 검사한다."""

import httpx
import pytest

from app.services.llm.gemini_provider import GeminiProvider, GeminiQuotaError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quota", "status", "retry_after", "expected", "attempts"),
    [
        ("RequestsPerDay", 429, "2", "daily", 1),
        ("RequestsPerMinute", 429, "2", "minute", 2),
        ("RequestsPerMinute", 429, "60", "minute", 1),
        ("Unclassified", 403, None, "unknown", 1),
    ],
)
async def test_quota_retries(quota, status, retry_after, expected, attempts, monkeypatch, caplog):
    requests, waits = [], []

    async def sleep(delay):
        waits.append(delay)

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Retry-After": retry_after} if retry_after else {},
            json={"error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "secret upstream body",
                "details": [
                    {"violations": [{"quotaId": quota}]},
                    {"retryDelay": "8s"},
                ],
            }},
        )

    monkeypatch.setattr("app.services.llm.gemini_provider.asyncio.sleep", sleep)
    provider = GeminiProvider(api_key="secret-key", base_url="https://gemini.test/v1beta",
                              chat_model="test-chat-model", embedding_model="test-embed-model",
                              timeout=1, embedding_dim=4)
    await provider.close()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(GeminiQuotaError) as error:
            await provider.generate([{"role": "user", "content": "secret input"}])
        assert error.value.kind == expected
        assert len(requests) == attempts
        assert waits == ([2] if attempts == 2 else [])
        assert requests[0].headers["x-goog-api-key"] == "secret-key"
        assert "secret" not in str(requests[0].url)
        assert "secret" not in caplog.text
        if expected == "minute":
            assert error.value.retry_after == int(retry_after)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_read_timeout_is_not_retried():
    from app.services.llm.gemini_provider import GeminiTimeoutError

    attempts = 0

    def time_out(request):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("upstream timeout", request=request)

    provider = GeminiProvider(api_key="test", base_url="https://gemini.test/v1beta",
                              chat_model="test-chat-model", embedding_model="test-embed-model",
                              timeout=1, embedding_dim=4)
    await provider.close()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(time_out))
    try:
        with pytest.raises(GeminiTimeoutError):
            await provider.generate([{"role": "user", "content": "test"}])
        assert attempts == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "budget", "level", "expected"),
    [
        ("gemini-3.5-flash", 0, None, {"thinkingLevel": "minimal"}),
        ("gemini-3.5-flash", -1, None, None),
        ("gemini-2.5-flash", 0, None, {"thinkingBudget": 0}),
        ("gemini-3.8-flash", 0, "low", {"thinkingLevel": "low"}),
    ],
)
async def test_generation_sends_only_one_thinking_control(model, budget, level, expected):
    import json

    def respond(request):
        body = json.loads(request.content)
        assert body["generationConfig"].get("thinkingConfig") == expected
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    provider = GeminiProvider(
        api_key="test", base_url="https://gemini.test/v1beta", chat_model=model,
        embedding_model="test-embed-model", timeout=1, embedding_dim=4,
        thinking_budget=budget, thinking_level=level,
    )
    await provider.close()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await provider.generate([{"role": "user", "content": "test"}], json_mode=True)
        assert result.text == "{}"
    finally:
        await provider.close()
