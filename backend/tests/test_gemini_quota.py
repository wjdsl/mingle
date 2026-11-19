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
async def test_quota_log_records_identifiers_without_message(caplog):
    """429 원본의 할당량 식별 필드는 남기고 오류 메시지·키·입력은 남기지 않는다."""

    def respond(request):
        return httpx.Response(429, json={"error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "secret upstream body",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                    "quotaDimensions": {"model": "test-chat-model", "location": "global"},
                    "quotaValue": "20",
                }]},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "39s"},
            ],
        }})

    provider = GeminiProvider(api_key="secret-key", base_url="https://gemini.test/v1beta",
                              chat_model="test-chat-model", embedding_model="test-embed-model",
                              timeout=1, embedding_dim=4, http_attempts=1)
    await provider.close()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with caplog.at_level("WARNING"), pytest.raises(GeminiQuotaError) as error:
            await provider.generate([{"role": "user", "content": "secret input"}])
        assert error.value.kind == "daily"
        line = next(r.getMessage() for r in caplog.records if "quota=daily" in r.getMessage())
        assert "metric=generativelanguage.googleapis.com/generate_content_free_tier_requests" in line
        assert "id=GenerateRequestsPerDayPerProjectPerModel-FreeTier" in line
        assert "dims=location:global,model:test-chat-model" in line
        assert "value=20" in line
        assert "retry_delay=39s" in line
        assert "retry_after_header=-" in line
        assert "secret" not in caplog.text
    finally:
        await provider.close()


def test_quota_log_fields_handles_missing_and_unsafe_values():
    from app.services.llm.gemini_provider import quota_log_fields

    empty = quota_log_fields(httpx.Response(429, text="not json"))
    assert empty == "violations=[-] retry_delay=- retry_after_header=-"

    unsafe = quota_log_fields(httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {"details": [
        {"violations": [{"quotaId": "PerDay\nfake=line {x}"}]},
    ]}}))
    assert "\n" not in unsafe and "{x}" not in unsafe
    assert "id=PerDay?fake?line??x?" in unsafe
    assert "metric=- " in unsafe and "dims=-" in unsafe and "value=-" in unsafe
    assert unsafe.endswith("retry_delay=- retry_after_header=7")


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
