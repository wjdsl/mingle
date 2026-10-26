"""OpenAI Chat Completions / Embeddings 공급자 (httpx 직접 호출)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx

from app.services.llm.base import LLMError, LLMProvider, LLMResult, fit_embedding


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        chat_model: str,
        embedding_model: str,
        timeout: float,
        embedding_dim: int,
    ) -> None:
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        payload: dict = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.8,
            "max_tokens": max_tokens or 700,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            response = await self._client.post(f"{self._base}/chat/completions", json=payload)
        except httpx.HTTPError as exc:  # 네트워크 오류
            raise LLMError(f"OpenAI 연결 실패: {exc}") from exc
        self._raise_for_status(response)
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMError("OpenAI 응답 형식이 올바르지 않습니다.") from exc
        usage = data.get("usage") or {}
        return LLMResult(
            text=text.strip(),
            provider=self.name,
            model=self.chat_model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.8,
            "max_tokens": max_tokens or 700,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST", f"{self._base}/chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "ignore")
                    raise LLMError(
                        f"OpenAI 스트리밍 오류 {response.status_code}: {body[:300]}"
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[len("data:") :].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        event = json.loads(chunk)
                        delta = event["choices"][0].get("delta", {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI 스트리밍 연결 실패: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self._client.post(
                f"{self._base}/embeddings",
                json={"model": self.embedding_model, "input": texts},
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI 임베딩 연결 실패: {exc}") from exc
        self._raise_for_status(response)
        data = response.json().get("data", [])
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [fit_embedding(item.get("embedding", []), self.embedding_dim) for item in ordered]

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise LLMError(
                f"OpenAI 오류 {response.status_code}: {response.text[:300]}"
            )
