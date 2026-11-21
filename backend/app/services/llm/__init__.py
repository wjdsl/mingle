"""LLM 공급자 레지스트리.

LLM_PROVIDER=auto 이면 키가 설정된 공급자를 자동 선택하고(OpenAI → Gemini → Mock; Qwen은 제외),
LLM_PROVIDER=qwen 을 명시했을 때만 Qwen을 사용한다.

아무 키도 없으면 MockProvider로 동작한다 (개발/시연/테스트용).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMError, LLMProvider, LLMResult, fit_embedding
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.mock import MockProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.qwen_provider import QwenProvider

logger = logging.getLogger(__name__)

_provider_override: str | None = None
_degraded_reason: str | None = None

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMResult",
    "ensure_llm_ready",
    "fit_embedding",
    "get_llm",
    "is_degraded",
    "reset_llm",
]


def _build_provider() -> LLMProvider:
    provider = _provider_override or settings.resolved_provider
    if provider == "openai":
        if not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY 없음 → mock 공급자로 대체")
            return MockProvider(settings.embedding_dim)
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            chat_model=settings.openai_chat_model,
            embedding_model=settings.openai_embedding_model,
            timeout=settings.llm_timeout_seconds,
            embedding_dim=settings.embedding_dim,
        )
    if provider == "gemini":
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY 없음 → mock 공급자로 대체")
            return MockProvider(settings.embedding_dim)
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            chat_model=settings.gemini_chat_model,
            embedding_model=settings.gemini_embedding_model,
            timeout=settings.llm_timeout_seconds,
            embedding_dim=settings.embedding_dim,
            thinking_budget=settings.gemini_thinking_budget,
            thinking_level=settings.gemini_thinking_level or None,
            http_attempts=settings.gemini_http_attempts,
        )
    if provider == "qwen":
        # 명시적으로 선택한 공급자이므로 설정이 불완전해도 Mock으로 대체하지 않고 오류를 낸다.
        missing = [
            name
            for name, value in (
                ("QWEN_API_URL", settings.qwen_api_url),
                ("QWEN_API_KEY", settings.qwen_api_key),
            )
            if not value
        ]
        if missing:
            raise LLMError(f"LLM_PROVIDER=qwen 이지만 {', '.join(missing)} 가 설정되지 않았습니다.")
        try:
            return QwenProvider(
                base_url=settings.qwen_api_url,
                api_key=settings.qwen_api_key,
                timeout=settings.qwen_timeout_seconds,
            )
        except ValueError as exc:
            raise LLMError(f"QWEN_API_URL 설정 오류: {exc}") from exc
    return MockProvider(settings.embedding_dim)


@lru_cache
def get_llm() -> LLMProvider:
    provider = _build_provider()
    logger.info("LLM 공급자: %s (model=%s)", provider.name, provider.chat_model)
    return provider


def reset_llm() -> None:
    """테스트/설정 변경 시 캐시 초기화."""
    global _provider_override, _degraded_reason
    _provider_override = None
    _degraded_reason = None
    get_llm.cache_clear()


def is_degraded() -> bool:
    return _degraded_reason is not None


def degraded_reason() -> str | None:
    return _degraded_reason


async def ensure_llm_ready() -> None:
    """공급자 키와 모델을 확인한다. Qwen은 점검 실패 후에도 선택을 유지한다.

    지원되는 임베딩과 생성 API를 각각 1회 호출한다.
    다른 공급자는 점검에 실패하면 오프라인 시연용 Mock으로 전환한다.
    """
    global _provider_override, _degraded_reason

    provider = get_llm()
    if provider.name == "mock":
        return

    try:
        # 임베딩을 지원하지 않는 공급자(Qwen)는 임베딩 확인을 건너뛴다. 생성 확인은 그대로 한다.
        if provider.supports_embedding:
            await provider.embed(["ping"])
        await provider.generate(
            [{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=8,
        )
    except LLMError as exc:
        _degraded_reason = str(exc)
        if provider.name == "qwen":
            logger.warning("Qwen 시작 점검 실패. 이후 요청에서 다시 연결합니다: %s", exc)
            return
        logger.warning(
            "LLM 공급자 '%s' 사용 불가 → Mock으로 대체합니다. 원인: %s",
            provider.name,
            exc,
        )
        _provider_override = "mock"
        get_llm.cache_clear()
        get_llm()
    except Exception as exc:  # pragma: no cover - 예상치 못한 공급자 오류
        _degraded_reason = type(exc).__name__
        if provider.name == "qwen":
            logger.warning("Qwen 시작 점검 오류. 이후 요청에서 다시 연결합니다: %s", _degraded_reason)
            return
        logger.warning("LLM 공급자 확인 중 오류 → Mock으로 대체: %s", _degraded_reason)
        _provider_override = "mock"
        get_llm.cache_clear()
        get_llm()
