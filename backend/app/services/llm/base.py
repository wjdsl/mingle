"""LLM 공급자 추상화."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(slots=True)
class ChatMessage:
    role: str  # system | user | assistant
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMError(RuntimeError):
    """LLM 호출 실패."""


class LLMProvider(ABC):
    name: str = "base"
    chat_model: str = "unknown"

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        ...


def fit_embedding(vector: list[float], dim: int) -> list[float]:
    """차원을 맞추고 L2 정규화한다. (공급자별 임베딩 차원 차이 흡수)"""
    values = [float(v) for v in (vector or [])][:dim]
    if len(values) < dim:
        values.extend([0.0] * (dim - len(values)))
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
