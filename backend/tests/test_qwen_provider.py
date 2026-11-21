"""QwenProvider 단위 테스트 — 실제 Colab API는 호출하지 않는다."""

import json

import httpx
import pytest

from app.services.llm.base import LLMError
from app.services.llm.qwen_provider import QwenError, QwenProvider


@pytest.fixture
async def provider_factory():
    providers = []

    def create(handler):
        provider = QwenProvider(
            base_url="https://qwen.example.test",
            api_key="test-secret",
            timeout=5.0,
        )

        original_client = provider._client
        provider._client = httpx.AsyncClient(
            base_url="https://qwen.example.test",
            headers={"Authorization": "Bearer test-secret"},
            transport=httpx.MockTransport(handler),
        )
        providers.append((provider, original_client))
        return provider

    yield create

    for provider, original_client in providers:
        await provider.close()
        await original_client.aclose()


@pytest.mark.asyncio
async def test_generate_success(provider_factory):
    def handler(request):
        assert request.url.path == "/generate"
        assert request.headers["Authorization"] == "Bearer test-secret"

        payload = json.loads(request.content)
        assert payload["max_new_tokens"] == 150

        return httpx.Response(
            200,
            json={
                "response": "안녕하세요!",
                "model": "Qwen2.5-3B-Instruct-EXP-004",
            },
        )

    provider = provider_factory(handler)
    result = await provider.generate(
        [{"role": "user", "content": "안녕"}]
    )

    assert result.text == "안녕하세요!"
    assert result.provider == "qwen"
    assert result.model == "Qwen2.5-3B-Instruct-EXP-004"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 503])
async def test_generate_http_error(provider_factory, status):
    provider = provider_factory(
        lambda request: httpx.Response(status)
    )

    with pytest.raises(LLMError, match=str(status)):
        await provider.generate(
            [{"role": "user", "content": "안녕"}]
        )


@pytest.mark.asyncio
async def test_generate_invalid_response(provider_factory):
    provider = provider_factory(
        lambda request: httpx.Response(
            200, json={"unexpected": True}
        )
    )

    with pytest.raises(LLMError):
        await provider.generate(
            [{"role": "user", "content": "안녕"}]
        )


async def test_offline_ngrok_tunnel_is_a_connection_error(provider_factory):
    provider = provider_factory(lambda request: httpx.Response(404, text="<html>ERR_NGROK_3200</html>"))

    with pytest.raises(QwenError, match="ERR_NGROK_3200") as error:
        await provider.generate([{"role": "user", "content": "안녕"}])

    assert error.value.kind == "connection"


@pytest.mark.asyncio
async def test_json_mode_unsupported(provider_factory):
    provider = provider_factory(
        lambda request: httpx.Response(200, json={})
    )

    with pytest.raises(LLMError, match="JSON"):
        await provider.generate(
            [{"role": "user", "content": "안녕"}],
            json_mode=True,
        )


@pytest.mark.asyncio
async def test_token_limit(provider_factory):
    provider = provider_factory(
        lambda request: httpx.Response(200, json={})
    )

    with pytest.raises(LLMError, match="300"):
        await provider.generate(
            [{"role": "user", "content": "안녕"}],
            max_tokens=700,
        )


@pytest.mark.asyncio
async def test_embedding_unsupported(provider_factory):
    provider = provider_factory(
        lambda request: httpx.Response(200, json={})
    )

    with pytest.raises(LLMError, match="임베딩"):
        await provider.embed(["hello"])


@pytest.mark.asyncio
async def test_stream_unsupported(provider_factory):
    provider = provider_factory(
        lambda request: httpx.Response(200, json={})
    )

    with pytest.raises(LLMError, match="스트리밍"):
        async for _ in provider.stream(
            [{"role": "user", "content": "안녕"}]
        ):
            pass


@pytest.mark.asyncio
async def test_generate_timeout(provider_factory):
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    provider = provider_factory(handler)

    with pytest.raises(LLMError, match="시간 초과"):
        await provider.generate(
            [{"role": "user", "content": "안녕"}]
        )
