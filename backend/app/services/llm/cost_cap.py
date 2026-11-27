"""LLM 일일 비용 상한 래퍼."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.config import settings
from app.services.llm.base import LLMError, LLMProvider, LLMResult

logger = logging.getLogger(__name__)


class DailyCostCapExceeded(LLMError):
    pass


class CostCappedProvider(LLMProvider):
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self.name = provider.name
        self.chat_model = provider.chat_model
        self.supports_embedding = provider.supports_embedding
        self.supports_streaming = provider.supports_streaming
        self.max_tokens_limit = provider.max_tokens_limit
        self._spent: dict[str, float] = {}

    def __getattr__(self, name: str) -> Any:
        # 래퍼에 없는 공급자 속성(supports_json_schema, thinking_level, http_attempts 등)은
        # 감싼 공급자의 값을 그대로 돌려준다. 호출 측은 getattr로 이 값을 확인한다.
        if name == "_provider":
            raise AttributeError(name)
        return getattr(self._provider, name)

    def _today(self) -> str:
        return date.today().isoformat()

    def _spent_today(self) -> float:
        return self._spent.get(self._today(), 0.0)

    def _add_cost(self, prompt_tokens: int | None, completion_tokens: int | None) -> None:
        cap = settings.daily_llm_cost_cap_usd
        if cap <= 0:
            return
        price = settings.llm_cost_per_1k_tokens_usd
        tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        cost = tokens * price / 1000.0
        key = self._today()
        self._spent[key] = self._spent.get(key, 0.0) + cost

    def _check_cap(self) -> None:
        cap = settings.daily_llm_cost_cap_usd
        if cap > 0 and self._spent_today() >= cap:
            raise DailyCostCapExceeded("일일 LLM 비용 상한에 도달했습니다.")

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False, **kwargs) -> LLMResult:
        # json_schema처럼 공급자별 추가 인자는 그대로 넘긴다.
        self._check_cap()
        result = await self._provider.generate(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode, **kwargs
        )
        self._add_cost(result.prompt_tokens, result.completion_tokens)
        return result

    async def embed(self, texts):
        self._check_cap()
        return await self._provider.embed(texts)

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        self._check_cap()
        async for chunk in self._provider.stream(messages, temperature=temperature, max_tokens=max_tokens):
            yield chunk