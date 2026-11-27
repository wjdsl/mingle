"""비용 상한 래퍼(CostCappedProvider)가 감싼 공급자의 기능을 가리지 않는지 확인한다.

래퍼가 supports_json_schema를 숨기면 스토리 턴에서 Gemini 응답 스키마가 빠지고,
json_schema 인자를 막으면 스키마를 넘길 수 없다. 외부 API는 호출하지 않는다.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.llm.base import LLMProvider, LLMResult
from app.services.llm.cost_cap import CostCappedProvider, DailyCostCapExceeded


class _SchemaProvider(LLMProvider):
    name = "gemini"
    chat_model = "fake-model"
    supports_json_schema = True
    thinking_level = "minimal"
    http_attempts = 2

    def __init__(self) -> None:
        self.kwargs: dict = {}

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False, json_schema=None):
        self.kwargs = {"json_mode": json_mode, "json_schema": json_schema}
        return LLMResult(text="{}", provider=self.name, model=self.chat_model, prompt_tokens=500, completion_tokens=500)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


def test_wrapper_exposes_inner_provider_attributes():
    wrapped = CostCappedProvider(_SchemaProvider())
    assert wrapped.name == "gemini"
    assert getattr(wrapped, "supports_json_schema", False) is True
    assert getattr(wrapped, "thinking_level", None) == "minimal"
    assert getattr(wrapped, "http_attempts", None) == 2
    assert getattr(wrapped, "not_an_attribute", "기본값") == "기본값"


async def test_wrapper_passes_json_schema_to_inner_provider():
    inner = _SchemaProvider()
    wrapped = CostCappedProvider(inner)
    schema = {"type": "object"}
    await wrapped.generate([{"role": "user", "content": "hi"}], json_mode=True, json_schema=schema)
    assert inner.kwargs == {"json_mode": True, "json_schema": schema}


async def test_wrapper_still_enforces_daily_cap(monkeypatch):
    monkeypatch.setattr(settings, "daily_llm_cost_cap_usd", 0.001)
    monkeypatch.setattr(settings, "llm_cost_per_1k_tokens_usd", 0.002)
    wrapped = CostCappedProvider(_SchemaProvider())
    await wrapped.generate([{"role": "user", "content": "hi"}])  # 1000토큰 → 0.002달러
    try:
        await wrapped.generate([{"role": "user", "content": "hi"}])
    except DailyCostCapExceeded:
        return
    raise AssertionError("상한을 넘긴 뒤에도 호출이 허용되었다")
