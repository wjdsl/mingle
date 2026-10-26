"""LLM 공급자 레지스트리.

LLM_PROVIDER=auto 이면 키가 설정된 공급자를 자동 선택하고,
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
        )
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
    """공급자 키/모델이 실제로 동작하는지 확인하고, 실패하면 Mock으로 대체한다.

    - 임베딩과 생성 API를 각각 1회씩 가볍게 호출한다.
    - 키가 잘못되었거나 모델이 폐기된 경우에도 서버는 정상 기동되며,
      오프라인 Mock 모드로 전체 기능을 시연할 수 있다.
    """
    global _provider_override, _degraded_reason

    provider = get_llm()
    if provider.name == "mock":
        return

    try:
        await provider.embed(["ping"])
        await provider.generate(
            [{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=8,
        )
    except LLMError as exc:
        _degraded_reason = str(exc)
        logger.warning(
            "LLM 공급자 '%s' 사용 불가 → Mock으로 대체합니다. 원인: %s",
            provider.name,
            exc,
        )
        _provider_override = "mock"
        get_llm.cache_clear()
        get_llm()
    except Exception as exc:  # pragma: no cover - 예상치 못한 공급자 오류
        _degraded_reason = str(exc)
        logger.exception("LLM 공급자 확인 중 오류 → Mock으로 대체")
        _provider_override = "mock"
        get_llm.cache_clear()
        get_llm()
