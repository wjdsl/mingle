"""Gemini 5xx 진단 로그와 실패 로그 파일 보존을 외부 요청 없이 검사한다."""

import logging

import httpx
import pytest

from app.core.logging import FAILURE_LOGGERS, configure_failure_log
from app.services.llm.gemini_provider import GeminiHTTPError, GeminiProvider, server_error_log_fields


def _unavailable(retry_after: str | None = None) -> httpx.Response:
    return httpx.Response(
        503,
        headers={"Retry-After": retry_after} if retry_after else {},
        json={"error": {
            "code": 503,
            "status": "UNAVAILABLE",
            "message": "secret upstream body: The model is overloaded",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "MODEL_OVERLOADED",
                 "domain": "googleapis.com", "metadata": {"service": "secret-metadata"}},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"},
            ],
        }},
    )


async def _provider(respond, monkeypatch, attempts: int) -> tuple[GeminiProvider, list[float]]:
    waits: list[float] = []

    async def sleep(delay):
        waits.append(delay)

    monkeypatch.setattr("app.services.llm.gemini_provider.asyncio.sleep", sleep)
    provider = GeminiProvider(api_key="secret-key", base_url="https://gemini.test/v1beta",
                              chat_model="test-chat-model", embedding_model="test-embed-model",
                              timeout=1, embedding_dim=4, http_attempts=attempts)
    await provider.close()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return provider, waits


@pytest.mark.asyncio
async def test_503_logs_classification_and_retry_after_without_sensitive_data(monkeypatch, caplog):
    requests = []

    def respond(request):
        requests.append(request)
        return _unavailable("10")

    provider, waits = await _provider(respond, monkeypatch, attempts=2)
    try:
        with caplog.at_level("WARNING"), pytest.raises(GeminiHTTPError) as error:
            await provider.generate([{"role": "system", "content": "secret prompt"},
                                     {"role": "user", "content": "secret input"}])
        assert error.value.status_code == 503
        # 기존 재시도 정책(503은 1회 재시도, 1초 대기)은 그대로다.
        assert len(requests) == 2 and waits == [1]
        lines = [r.getMessage() for r in caplog.records if "status=503" in r.getMessage()]
        assert len(lines) == 2
        assert "attempt=1/2 status=503 will_retry=true" in lines[0]
        assert "attempt=2/2 status=503 will_retry=false" in lines[1]
        for line in lines:
            assert "operation=generateContent" in line
            assert "error_status=UNAVAILABLE error_code=503" in line
            assert "detail_types=ErrorInfo,RetryInfo reason=MODEL_OVERLOADED" in line
            assert "retry_delay=12s retry_after_header=10" in line
        assert "secret" not in caplog.text
        assert "overloaded" not in caplog.text
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_429_log_is_unchanged_by_server_error_logging(monkeypatch, caplog):
    def respond(request):
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED",
                                                   "details": [{"violations": [{"quotaId": "RequestsPerDay"}]}]}})

    provider, _ = await _provider(respond, monkeypatch, attempts=2)
    try:
        with caplog.at_level("WARNING"), pytest.raises(Exception):
            await provider.generate([{"role": "user", "content": "hi"}])
        assert any("quota=daily" in r.getMessage() for r in caplog.records)
        assert not any("error_status=" in r.getMessage() for r in caplog.records)
    finally:
        await provider.close()


def test_server_error_fields_without_body_or_header():
    assert server_error_log_fields(httpx.Response(503, text="<html>secret</html>")) == (
        "error_status=- error_code=- detail_types=- reason=- retry_delay=- retry_after_header=-"
    )
    unsafe = server_error_log_fields(httpx.Response(503, json={"error": {
        "status": "UNAVAILABLE\nfake=1", "details": [{"@type": "x.y.ErrorInfo", "reason": "a b{c}"}],
    }}))
    assert "\n" not in unsafe and "{" not in unsafe
    assert "error_status=UNAVAILABLE?fake?1" in unsafe and "reason=a?b?c?" in unsafe


def test_failure_log_file_keeps_only_reviewed_loggers(tmp_path):
    path = tmp_path / "logs" / "llm-failures.log"
    try:
        assert configure_failure_log(str(path)) == path.resolve()
        # 같은 프로세스에서 다시 설정해도 핸들러가 중복되지 않는다.
        configure_failure_log(str(path))
        logging.getLogger(FAILURE_LOGGERS[0]).warning("provider=gemini status=503 kept")
        logging.getLogger(FAILURE_LOGGERS[0]).info("provider=gemini status=200 info-dropped")
        logging.getLogger("app.api.routes.chat").warning("other route dropped")
        for name in FAILURE_LOGGERS:
            for handler in logging.getLogger(name).handlers:
                handler.flush()
        text = path.read_text(encoding="utf-8")
        assert text.count("status=503 kept") == 1
        assert "info-dropped" not in text and "other route" not in text
    finally:
        for name in FAILURE_LOGGERS:
            logger = logging.getLogger(name)
            for handler in [h for h in logger.handlers if h.get_name() == "llm-failure-file"]:
                logger.removeHandler(handler)
                handler.close()
    assert configure_failure_log("") is None
