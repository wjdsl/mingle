"""Google Gemini 공급자 (generateContent / batchEmbedContents)."""

from __future__ import annotations

import asyncio
import re
import time
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections.abc import AsyncIterator

import httpx

from app.services.llm.base import LLMError, LLMProvider, LLMResult, fit_embedding

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = {500, 502, 503, 504}
MAX_RETRY_WAIT = 15


class GeminiTimeoutError(LLMError):
    """Gemini 응답 시간 초과."""


class GeminiHTTPError(LLMError):
    def __init__(self, status_code: int):
        super().__init__(f"Gemini 오류 {status_code}")
        self.status_code = status_code


class GeminiQuotaError(LLMError):
    def __init__(self, kind: str, retry_after: int | None):
        super().__init__(f"Gemini quota: {kind}")
        self.kind = kind
        self.retry_after = retry_after


_SAFE_LOG_VALUE = re.compile(r"[^A-Za-z0-9._:/\-]")


def _safe(value: object) -> str:
    """할당량 식별자만 로그에 남기도록 허용 문자 외에는 '?'로 바꾸고 길이를 제한한다."""
    return _SAFE_LOG_VALUE.sub("?", str(value))[:120]


def quota_log_fields(response: httpx.Response) -> str:
    """429 응답의 할당량 식별 필드만 요약한다(오류 메시지 원문·요청 내용은 남기지 않는다).

    QuotaFailure.violations[]의 quotaMetric·quotaId·quotaDimensions·quotaValue와
    RetryInfo.retryDelay, Retry-After 헤더. 필드가 없으면 '-'로 표시한다.
    """
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    details = error.get("details") if isinstance(error.get("details"), list) else []
    violations: list[str] = []
    retry_delay = "-"
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if "retryDelay" in detail:
            retry_delay = _safe(detail["retryDelay"])
        for violation in detail.get("violations") or []:
            if not isinstance(violation, dict):
                continue
            dims = violation.get("quotaDimensions")
            dims_text = (
                ",".join(f"{_safe(k)}:{_safe(v)}" for k, v in sorted(dims.items()))
                if isinstance(dims, dict) and dims else "-"
            )
            violations.append(
                "{metric=%s id=%s dims=%s value=%s}" % (
                    _safe(violation.get("quotaMetric", "-")),
                    _safe(violation.get("quotaId", "-")),
                    dims_text,
                    _safe(violation.get("quotaValue", "-")),
                )
            )
    header = response.headers.get("Retry-After")
    return "violations=[%s] retry_delay=%s retry_after_header=%s" % (
        " ".join(violations) or "-", retry_delay, _safe(header) if header else "-",
    )


def server_error_log_fields(response: httpx.Response) -> str:
    """5xx 응답의 분류 필드만 요약한다(오류 메시지 원문·metadata·요청 내용은 남기지 않는다).

    error.status(예: UNAVAILABLE)·error.code, details[]의 @type 이름과 ErrorInfo.reason,
    RetryInfo.retryDelay, Retry-After 헤더. 필드가 없으면 '-'로 표시한다.
    """
    try:
        body = response.json()
        error = (body.get("error") if isinstance(body, dict) else None) or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    details = error.get("details") if isinstance(error.get("details"), list) else []
    types: list[str] = []
    reason = "-"
    retry_delay = "-"
    for detail in details:
        if not isinstance(detail, dict):
            continue
        kind = str(detail.get("@type", "")).rsplit(".", 1)[-1]
        if kind:
            types.append(_safe(kind))
        if "reason" in detail:
            reason = _safe(detail["reason"])
        if "retryDelay" in detail:
            retry_delay = _safe(detail["retryDelay"])
    header = response.headers.get("Retry-After")
    return "error_status=%s error_code=%s detail_types=%s reason=%s retry_delay=%s retry_after_header=%s" % (
        _safe(error.get("status", "-")),
        _safe(error.get("code", "-")),
        ",".join(types) or "-",
        reason,
        retry_delay,
        _safe(header) if header else "-",
    )


def _quota_error(response: httpx.Response) -> GeminiQuotaError | None:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if response.status_code != 429 and error.get("status") != "RESOURCE_EXHAUSTED":
        return None
    details = error.get("details") or []
    identifiers = " ".join(
        str(violation.get(key, ""))
        for detail in details
        for violation in detail.get("violations", [])
        for key in ("quotaId", "quotaMetric", "description")
    )
    quota_text = (identifiers + " " + str(error.get("message", ""))).lower()
    if any(marker in quota_text for marker in ("perday", "per_day", "per day", "daily", "rpd")):
        return GeminiQuotaError("daily", None)

    delay = None
    header = response.headers.get("Retry-After")
    if header:
        try:
            delay = max(0, int(header))
        except ValueError:
            try:
                delay = max(0, int((parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()) + 1)
            except (ValueError, TypeError, OverflowError):
                pass
    if delay is None:
        for detail in details:
            hint = detail.get("retryDelay")
            if isinstance(hint, str) and hint.endswith("s"):
                try:
                    delay = max(0, int(float(hint[:-1])) + 1)
                except (ValueError, OverflowError):
                    continue
                break
    minute = any(marker in quota_text for marker in ("perminute", "per_minute", "per minute", "rpm"))
    return GeminiQuotaError("minute" if minute else "unknown", delay)


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_json_schema = True  # generationConfig.responseJsonSchema 전달 가능

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        chat_model: str,
        embedding_model: str,
        timeout: float,
        embedding_dim: int,
        thinking_budget: int = 0,
        http_attempts: int = 2,
        thinking_level: str | None = None,
    ) -> None:
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self.thinking_budget = thinking_budget
        self.thinking_level = thinking_level
        if self.thinking_level is None and chat_model == "gemini-3.5-flash" and thinking_budget == 0:
            self.thinking_level = "minimal"
        self.http_attempts = http_attempts
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, url: str, *, json: dict) -> httpx.Response:
        headers = {"x-goog-api-key": self._api_key}
        operation = url.rsplit(":", 1)[-1]
        model = self.chat_model if operation == "generateContent" else self.embedding_model
        attempts = self.http_attempts
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            delay = 2 ** (attempt - 1)
            headers_ms = None
            try:
                async with self._client.stream("POST", url, json=json, headers=headers) as response:
                    headers_ms = int((time.perf_counter() - started) * 1000)
                    await response.aread()
            except httpx.HTTPError as exc:
                # 타임아웃 뒤에는 공급자가 이미 생성했을 수 있으므로 자동 재전송하지 않는다.
                logger.warning(
                    "provider=gemini model=%s operation=%s attempt=%d error=%s phase=%s headers_ms=%s latency_ms=%d",
                    model, operation, attempt, type(exc).__name__,
                    "before_headers" if headers_ms is None else "response_body",
                    headers_ms, (time.perf_counter() - started) * 1000,
                )
                if isinstance(exc, httpx.TimeoutException):
                    raise GeminiTimeoutError("Gemini 응답 시간 초과") from exc
                raise LLMError("Gemini 연결 실패") from exc
            logger.info(
                "provider=gemini model=%s operation=%s attempt=%d status=%d headers_ms=%s latency_ms=%d",
                model, operation, attempt, response.status_code, headers_ms, (time.perf_counter() - started) * 1000,
            )
            quota = _quota_error(response) if response.is_error else None
            if quota:
                delay = quota.retry_after if quota.retry_after is not None else max(2, delay)
                logger.warning(
                    "provider=gemini model=%s quota=%s retry_after=%s %s",
                    model, quota.kind, quota.retry_after, quota_log_fields(response),
                )
                if quota.kind != "minute" or delay > MAX_RETRY_WAIT or attempt == attempts:
                    raise quota
            elif response.status_code >= 500:
                will_retry = response.status_code in RETRYABLE_STATUS and attempt < attempts
                logger.warning(
                    "provider=gemini model=%s operation=%s attempt=%d/%d status=%d will_retry=%s %s",
                    model, operation, attempt, attempts, response.status_code,
                    str(will_retry).lower(), server_error_log_fields(response),
                )
                if not will_retry:
                    return response
            elif response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                return response
            await asyncio.sleep(delay)
        raise AssertionError("Gemini retry loop exhausted")

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> LLMResult:
        system, contents = self._convert(messages)
        generation_config: dict = {
            "temperature": temperature if temperature is not None else 0.8,
            "maxOutputTokens": max_tokens or 700,
        }
        if json_mode or json_schema is not None:
            generation_config["responseMimeType"] = "application/json"
        if json_schema is not None:
            # REST generateContent의 JSON Schema 필드(구형 responseSchema와 함께 쓰지 않는다).
            generation_config["responseJsonSchema"] = json_schema
        if self.thinking_level is not None:
            generation_config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        elif self.thinking_budget >= 0:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": self.thinking_budget
            }
        payload = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        started = time.perf_counter()
        url = f"{self._base}/models/{self.chat_model}:generateContent"
        response = await self._post(url, json=payload)
        self._raise_for_status(response)
        data = response.json()
        usage = data.get("usageMetadata") or {}
        candidates = data.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        logger.info(
            "provider=gemini model=%s input_tokens=%s output_tokens=%s thinking_tokens=%s finish_reason=%s",
            self.chat_model, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"),
            usage.get("thoughtsTokenCount"), candidate.get("finishReason"),
        )
        try:
            parts = candidate["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        except (KeyError, TypeError) as exc:
            raise LLMError("Gemini 응답 형식이 올바르지 않습니다.") from exc
        return LLMResult(
            text=text.strip(),
            provider=self.name,
            model=self.chat_model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        # 안정성을 위해 일반 생성 후 청크 단위로 전달한다.
        result = await self.generate(messages, temperature=temperature, max_tokens=max_tokens)
        step = 18
        for index in range(0, len(result.text), step):
            yield result.text[index : index + step]
            await asyncio.sleep(0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = {
            "requests": [
                {
                    "model": f"models/{self.embedding_model}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self.embedding_dim,
                }
                for text in texts
            ]
        }
        url = f"{self._base}/models/{self.embedding_model}:batchEmbedContents"
        response = await self._post(url, json=body)
        if response.status_code == 400:
            # 일부 모델은 outputDimensionality를 지원하지 않는다.
            for request in body["requests"]:
                request.pop("outputDimensionality", None)
            response = await self._post(url, json=body)
        self._raise_for_status(response)
        embeddings = response.json().get("embeddings", [])
        return [
            fit_embedding(item.get("values", []), self.embedding_dim) for item in embeddings
        ]

    @staticmethod
    def _convert(messages: list[dict[str, str]]) -> tuple[str, list[dict]]:
        system_parts: list[str] = []
        contents: list[dict] = []
        for message in messages:
            role = message["role"]
            if role == "system":
                system_parts.append(message["content"])
                continue
            gemini_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].append({"text": message["content"]})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": message["content"]}]})
        return "\n\n".join(system_parts), contents

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise GeminiHTTPError(response.status_code)
