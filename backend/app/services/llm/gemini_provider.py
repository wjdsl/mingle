"""Google Gemini 공급자 (generateContent / batchEmbedContents)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx

from app.services.llm.base import LLMError, LLMProvider, LLMResult, fit_embedding

# 재시도 대상: 일시적인 과부하/레이트리밋 응답
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GeminiProvider(LLMProvider):
    name = "gemini"

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
    ) -> None:
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self.thinking_budget = thinking_budget
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(
        self,
        url: str,
        *,
        json: dict,
        params: dict | None = None,
        attempts: int = 3,
    ) -> httpx.Response:
        """일시적 오류(429/5xx/타임아웃)는 짧은 백오프로 재시도한다."""
        params = params or {"key": self._api_key}
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(url, params=params, json=json)
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.HTTPError as exc:
                raise LLMError(f"Gemini 연결 실패: {exc}") from exc
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_error = LLMError(
                    f"Gemini 오류 {response.status_code}: {response.text[:200]}"
                )
            if attempt < attempts:
                await asyncio.sleep(0.7 * attempt)
        raise LLMError(f"Gemini 재시도 실패: {last_error}") from last_error

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        system, contents = self._convert(messages)
        generation_config: dict = {
            "temperature": temperature if temperature is not None else 0.8,
            "maxOutputTokens": max_tokens or 700,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if self.thinking_budget is not None and self.thinking_budget >= 0:
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
        if response.status_code == 400 and "thinkingConfig" in generation_config:
            # thinking 설정을 지원하지 않는 모델은 설정을 빼고 재시도한다.
            generation_config.pop("thinkingConfig", None)
            response = await self._post(url, json=payload)
        self._raise_for_status(response)
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError) as exc:
            raise LLMError("Gemini 응답 형식이 올바르지 않습니다.") from exc
        usage = data.get("usageMetadata") or {}
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
            raise LLMError(f"Gemini 오류 {response.status_code}: {response.text[:300]}")
