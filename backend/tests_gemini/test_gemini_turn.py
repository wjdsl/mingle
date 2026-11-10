import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import pytest
import httpx
from google.genai.errors import ClientError, ServerError
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas import TurnRequest, TurnResponse
from backend.gemini import NotConfigured, RESPONSE_SCHEMA, generate_turn

client = TestClient(app)


def payload():
    return {"requestId": "one", "turn": 1, "input": {"kind": "text", "text": "같이 가자"},
            "history": [{"role": "character", "text": "강의실이 어디죠?"}]}


def test_response_and_retry_contract():
    async def generate(request):
        assert request.requestId == "one"
        return TurnResponse(text="선배, 고마워요!", emotion="happy")
    with patch("backend.main.generate_turn", generate):
        for _ in range(2):
            response = client.post("/api/chat/turn", json=payload())
            assert response.status_code == 200
            assert response.json() == {"text": "선배, 고마워요!", "emotion": "happy"}


@pytest.mark.parametrize("change", [
    {"turn": 3}, {"input": {"kind": "text", "text": " "}},
    {"input": {"kind": "text", "text": "가" * 301}},
    {"input": {"kind": "choice", "text": "인사하고 들어가자", "choiceId": "greet"}},
    {"history": []},
])
def test_invalid_input_never_calls_provider(change):
    with patch("backend.main.generate_turn") as provider:
        assert client.post("/api/chat/turn", json={**payload(), **change}).status_code == 422
        provider.assert_not_called()


@pytest.mark.parametrize("error, status", [(NotConfigured(), 503), (asyncio.TimeoutError(), 504),
                                         (RuntimeError("private-provider-details"), 502)])
def test_sanitized_errors(error, status):
    async def fail(_request):
        raise error
    with patch("backend.main.generate_turn", fail):
        response = client.post("/api/chat/turn", json=payload())
        assert response.status_code == status
        assert "private-provider-details" not in response.text


@pytest.mark.parametrize("result", ['{"text":"좋아요","emotion":"happy"}',
                                    '{"text":"좋아요","emotion":"angry"}', '',
                                    '{"text":" ","emotion":"happy"}'])
def test_sdk_prompt_and_output(result):
    class FakeAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        @property
        def models(self):
            return self
        async def generate_content(self, **kwargs):
            assert kwargs['model'] == 'gemini-3.8-flash'
            assert kwargs['config'].thinking_config is None
            assert kwargs['config'].http_options is None
            assert "신입생 **푸르마**" in kwargs['config'].system_instruction
            assert kwargs['config'].response_schema is RESPONSE_SCHEMA
            assert RESPONSE_SCHEMA.additional_properties is None
            assert "같이 가자" in kwargs['contents']
            return SimpleNamespace(text=result)
    with patch('backend.gemini.dotenv_values', return_value={'GEMINI_API_KEY': 'test-placeholder'}), \
         patch('backend.gemini.genai.Client', return_value=SimpleNamespace(aio=FakeAsyncClient())), \
         patch('backend.gemini.asyncio.wait_for', wraps=asyncio.wait_for) as deadline:
        if result == '{"text":"좋아요","emotion":"happy"}':
            assert asyncio.run(generate_turn(TurnRequest(**payload()))).emotion == 'happy'
        else:
            with pytest.raises(ValueError):
                asyncio.run(generate_turn(TurnRequest(**payload())))
        assert deadline.call_args.kwargs['timeout'] == 125


@pytest.mark.parametrize("settings", [{}, {"GEMINI_API_KEY": None},
                                     {"GEMINI_API_KEY": ""}, {"GEMINI_API_KEY": "   "}])
def test_key_missing_does_not_create_sdk_client(settings):
    with patch('backend.gemini.dotenv_values', return_value=settings), patch('backend.gemini.genai.Client') as sdk:
        response = client.post('/api/chat/turn', json=payload())
        assert response.status_code == 503
        assert 'GEMINI_API_KEY' in response.json()['detail']
        sdk.assert_not_called()


@pytest.mark.parametrize("error, category, status, upstream", [
    (ClientError(400, {'error': {'message': 'private-provider-details'}}), 'invalid_request', 502, 400),
    (ClientError(401, {}), 'authentication', 502, 401),
    (ClientError(403, {}), 'permission', 502, 403),
    (ClientError(404, {}), 'model_not_found', 502, 404),
    (ClientError(429, {}), 'quota', 502, 429),
    (ServerError(503, {}), 'provider_unavailable', 502, 503),
    (ServerError(504, {}), 'provider_timeout', 502, 504),
    (httpx.ConnectError('private-provider-details'), 'network', 502, None),
    (httpx.ReadTimeout('private-provider-details'), 'timeout', 504, None),
])
def test_safe_failure_logs(error, category, status, upstream, caplog):
    async def fail(_request):
        raise error
    data = payload()
    data['requestId'] = 'private-client-request-id'
    with patch('backend.main.generate_turn', fail):
        response = client.post('/api/chat/turn', json=data)
    assert response.status_code == status
    assert f'category={category}' in caplog.text
    assert f'upstream_http={upstream}' in caplog.text
    for secret in ['private-provider-details', data['requestId'], data['input']['text'], data['history'][0]['text']]:
        assert secret not in caplog.text
        assert secret not in response.text


def test_output_validation_failure_is_logged_without_response(caplog):
    async def invalid(_request):
        return TurnResponse(text='private-output', emotion='invalid')
    with patch('backend.main.generate_turn', invalid):
        assert client.post('/api/chat/turn', json=payload()).status_code == 502
    assert 'category=output_validation' in caplog.text
    assert 'private-output' not in caplog.text


@pytest.mark.parametrize('errors, expected_calls, status', [
    ([ServerError(503, {})], 2, 200),
    ([ServerError(503, {}), ServerError(503, {})], 2, 502),
    ([ClientError(429, {})], 1, 502),
    ([ServerError(504, {})], 1, 502),
    ([httpx.ReadTimeout('private-provider-details')], 1, 504),
    ([ClientError(400, {})], 1, 502),
])
def test_sdk_retry_only_once_for_503(errors, expected_calls, status):
    from unittest.mock import AsyncMock
    generate = AsyncMock(side_effect=errors + [SimpleNamespace(text='{"text":"좋아요","emotion":"happy"}')])
    class FakeClient:
        models = SimpleNamespace(generate_content=generate)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    with patch('backend.gemini.dotenv_values', return_value={'GEMINI_API_KEY': 'test-placeholder'}), \
         patch('backend.gemini.genai.Client', return_value=SimpleNamespace(aio=FakeClient())) as sdk, \
         patch('backend.gemini.asyncio.sleep', new_callable=AsyncMock) as sleep:
        assert client.post('/api/chat/turn', json=payload()).status_code == status
        assert generate.await_count == expected_calls
        assert sdk.call_args.kwargs['http_options'].retry_options.attempts == 1
        assert sdk.call_args.kwargs['http_options'].timeout == 60000
        assert sleep.await_count == (1 if expected_calls == 2 else 0)
        if sleep.await_count:
            assert 1 <= sleep.call_args.args[0] <= 2


@pytest.mark.parametrize('stall', ['first', 'backoff', 'second'])
def test_total_deadline_covers_calls_and_backoff(stall):
    calls = []
    cancelled = []
    real_sleep = asyncio.sleep
    class FakeClient:
        @property
        def models(self):
            return self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def generate_content(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1 and stall != 'first':
                raise ServerError(503, {})
            try:
                await real_sleep(10)
            finally:
                cancelled.append(True)
    async def backoff(_delay):
        await real_sleep(10 if stall == 'backoff' else 0)
    with patch('backend.gemini.dotenv_values', return_value={'GEMINI_API_KEY': 'test-placeholder'}), \
         patch('backend.gemini.genai.Client', return_value=SimpleNamespace(aio=FakeClient())), \
         patch('backend.gemini.TOTAL_TIMEOUT_SECONDS', 0.03), \
         patch('backend.gemini.asyncio.sleep', backoff):
        assert client.post('/api/chat/turn', json=payload()).status_code == 504
    assert len(calls) == (2 if stall == 'second' else 1)
    assert bool(cancelled) == (stall != 'backoff')


def send_through_sdk(settings):
    # 실제 SDK가 만든 최종 HTTP 요청을 전송 직전에 가로챈다(네트워크 없음).
    from google.genai._api_client import BaseApiClient, HttpResponse
    sent = []
    async def capture(self, http_request, stream=False):
        sent.append(http_request)
        return HttpResponse({}, ['{"candidates":[{"content":{"role":"model","parts":'
                                 '[{"text":"{\\"text\\":\\"좋아요\\",\\"emotion\\":\\"happy\\"}"}]}}]}'])
    with patch('backend.gemini.dotenv_values', return_value={
            'GEMINI_API_KEY': 'test-placeholder', 'GEMINI_MODEL': 'gemini-3.5-flash', **settings}), \
         patch.object(BaseApiClient, '_async_request_once', capture):
        assert asyncio.run(generate_turn(TurnRequest(**payload()))).emotion == 'happy'
    assert len(sent) == 1
    return sent[0]


@pytest.mark.parametrize('level, expected', [
    (None, None), ('', None), ('   ', None), ('low', 'low'), (' LOW ', 'low'),
])
def test_thinking_level_rest_body(level, expected):
    import copy
    base = send_through_sdk({})
    request = send_through_sdk({} if level is None else {'GEMINI_THINKING_LEVEL': level})
    body = copy.deepcopy(request.data)
    assert body['generationConfig'].pop('thinkingConfig', None) == (
        None if expected is None else {'thinkingLevel': expected})
    # Thinking 외의 본문·헤더·URL·제한 시간은 설정이 없을 때와 같아야 한다.
    assert body == base.data
    assert request.headers == base.headers and request.url == base.url
    assert request.url.endswith('/v1beta/models/gemini-3.5-flash:generateContent')
    assert request.timeout == 60 and request.headers['X-Server-Timeout'] == '60'
    generation = base.data['generationConfig']
    assert 'thinkingConfig' not in generation
    assert generation['responseMimeType'] == 'application/json'
    assert generation['responseSchema']['required'] == ['text', 'emotion']
    assert generation['responseSchema']['properties']['emotion']['enum'] == ['confused', 'happy', 'sparkle']
    assert 'additionalProperties' not in generation['responseSchema']
    assert '신입생 **푸르마**' in base.data['systemInstruction']['parts'][0]['text']


@pytest.mark.parametrize('level', ['high', 'medium', 'minimal', 'lowest', '0', 'true'])
def test_invalid_thinking_level_is_setting_error(level, caplog):
    with patch('backend.gemini.dotenv_values', return_value={
            'GEMINI_API_KEY': 'test-placeholder', 'GEMINI_THINKING_LEVEL': level}), \
         patch('backend.gemini.genai.Client') as sdk:
        response = client.post('/api/chat/turn', json=payload())
    assert response.status_code == 503
    assert 'GEMINI_THINKING_LEVEL' in response.json()['detail']
    assert 'category=invalid_setting' in caplog.text
    sdk.assert_not_called()
