"""Colab에서 실행하는 MINGLE Qwen EXP-004 추론 API 클라이언트."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

from app.services.llm.base import LLMError, LLMProvider, LLMResult


class QwenError(LLMError):
    """Qwen 호출 실패. kind로 실패 유형을 구분한다(로그·Fallback 사유 기록용, 원문은 담지 않는다)."""

    def __init__(self, message: str, *, kind: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind  # timeout | connection | http | format
        self.status_code = status_code


class QwenProvider(LLMProvider):
    name = "qwen"
    # 기본값(True)을 상속하면 준비 검사·RAG가 embed()/stream()을 호출해 Mock으로 전환된다.
    supports_embedding = False
    supports_streaming = False
    max_tokens_limit = 300

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        if not base_url.startswith("https://") and not base_url.startswith(
            ("http://127.0.0.1:", "http://localhost:")
        ):
            raise ValueError(
                "Qwen API는 HTTPS 또는 로컬 HTTP 주소만 허용합니다."
            )

        self.chat_model = "Qwen2.5-3B-Instruct-EXP-004"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        if json_mode:
            raise LLMError(
                "Qwen 서버의 JSON 출력 모드는 아직 검증되지 않았습니다."
            )

        # Colab API는 현재 temperature를 지원하지 않음.
        # Colab EXP-004 서버는 현재 greedy decoding(do_sample=False)만 지원한다.
        # temperature 인자는 인터페이스 호환성을 위해 받지만 적용하지 않는다.

        requested_tokens = max_tokens if max_tokens is not None else 150

        # Colab Qwen API의 입력 메시지 길이 제한
        if len(messages) > 20:
            raise LLMError("Qwen은 최대 20개 메시지만 지원합니다.")

        for message in messages:
            if len(message.get("content", "")) > 12000:
                raise LLMError(
                    "Qwen은 메시지당 최대 12,000자만 지원합니다."
                )

        if not 1 <= requested_tokens <= 300:
            raise LLMError(
                "Qwen EXP-004는 현재 max_tokens 1~300만 지원합니다."
            )

        started = time.perf_counter()

        try:
            response = await self._client.post(
                "/generate",
                json={
                    "messages": messages,
                    "max_new_tokens": requested_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()

            text = data.get("response") if isinstance(data, dict) else None

            if not isinstance(text, str) or not text.strip():
                raise QwenError("Qwen 응답이 비어 있거나 형식이 잘못됐습니다.", kind="format")

            return LLMResult(
                text=text.strip(),
                provider=self.name,
                model=data.get("model", self.chat_model),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        except QwenError:
            raise
        except httpx.TimeoutException as exc:
            raise QwenError("Qwen 응답 시간 초과", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.headers.get("ngrok-error-code") == "ERR_NGROK_3200" or (
                exc.response.status_code == 404
                and "ERR_NGROK_3200" in exc.response.text
            ):
                raise QwenError(
                    "Qwen ngrok 터널이 오프라인입니다 (ERR_NGROK_3200).",
                    kind="connection",
                ) from exc
            raise QwenError(
                f"Qwen API HTTP 오류: {exc.response.status_code}",
                kind="http",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise QwenError("Qwen API 연결 실패", kind="connection") from exc
        except ValueError as exc:
            raise QwenError("Qwen API의 JSON 응답을 해석할 수 없습니다.", kind="format") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMError("Qwen 임베딩 기능은 아직 구현되지 않았습니다.")

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        raise LLMError("Qwen 스트리밍 기능은 아직 구현되지 않았습니다.")
        yield ""  # AsyncIterator 인터페이스 유지

    async def close(self) -> None:
        await self._client.aclose()
