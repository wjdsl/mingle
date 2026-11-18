"""냉장고 8턴 문장 수 위반·1턴 lines 타입 오류·지문 오염 대응 테스트.

외부 API 없이 가짜 공급자와 httpx.MockTransport로만 검증한다.
실제 Gemini 모델의 responseJsonSchema 호환성은 이 테스트로 확인하지 않는다(미검증).
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from app.core.config import settings
from app.services import story_turn_service
from app.services.llm.base import LLMProvider, LLMResult
from app.services.llm.gemini_provider import GeminiProvider
from app.services.story_prompt import build_story_messages, output_contract
from app.services.story_response_control import MAX_SENTENCES, Violation, correction_note, sentences, validate_lines
from app.services.story_scenes import get_project
from app.services.story_turn_service import normalize_display_tag, parse_story_output, story_response_schema

SCENARIO = "scenario_draft_v1"
FRONTEND_DISPLAY = re.compile(r"\[디스플레이: ([^\]]+)\]")  # StoryChat.tsx와 같은 패턴


def _intent_example(project_id: str, turn: int, intent_id: str) -> str:
    scene = get_project(project_id, SCENARIO).scenes[turn]
    direction = next(it.response_direction for it in scene.intents if it.id == intent_id)
    return re.findall(r"\"([^\"]+)\"", direction)[0]


# --- 문장 수 규칙(유지) ---

def test_sentence_limit_and_interjection_counting_are_unchanged():
    assert MAX_SENTENCES == 3
    assert sentences("흠흠. 제법이군. 고맙다는 뜻은 아니네.") == ["흠흠.", "제법이군.", "고맙다는 뜻은 아니네."]
    # 7·8턴 예시 대사는 감탄을 포함해 이미 상한(3문장)에 닿아 있다.
    assert len(sentences(_intent_example("fridge", 6, "fridge_t07_i01"))) == 3
    assert len(sentences(_intent_example("fridge", 7, "fridge_t08_i01"))) == 3


def test_four_sentences_with_interjection_still_violate():
    project = get_project("fridge", SCENARIO)
    four = "[디스플레이: 굳은 눈썹] …자네가 나를? 흠흠. 그럼 부탁하지. 오늘 밤은 문을 잠그게."
    three = "[디스플레이: 굳은 눈썹] …자네가 나를? 흠흠. 그럼 부탁하지."
    found = validate_lines(project, 7, [("냉장고 회장", four)], [], "민트")
    assert [(v.code, v.count) for v in found if v.code == "too_many_sentences"] == [("too_many_sentences", 4)]
    assert not [v for v in validate_lines(project, 7, [("냉장고 회장", three)], [], "민트") if v.code == "too_many_sentences"]


def test_correction_note_has_count_and_same_limit_only():
    note = correction_note([Violation("too_many_sentences", "냉장고 회장: 4문장", 4)])
    assert "4개" in note and "3문장 이하" in note and "흠흠." in note
    assert "냉장고 회장" not in note
    # 숫자가 없는 기존 형태의 위반도 기존 문구로 처리한다.
    assert correction_note([Violation("too_many_sentences", "x")]) == "문장이 3개를 넘었다. 1~3문장으로 줄인다."


@pytest.mark.parametrize("project_id", ["fridge", "cloud"])
def test_output_contract_states_counting_rule(project_id):
    project = get_project(project_id, SCENARIO)
    contract = output_contract(project, project.scenes[0])
    assert "1~3문장" in contract and "짧은 감탄도 한 문장으로 센다" in contract


# --- 진단 로그: 문장 수·코드만 ---

class FakeGemini(LLMProvider):
    name = "gemini"
    chat_model = "fake-gemini-model"
    supports_json_schema = True

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.kwargs: list[dict] = []

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False, json_schema=None):
        self.kwargs.append({"json_mode": json_mode, "json_schema": json_schema, "messages": messages})
        text = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        return LLMResult(text=text, provider=self.name, model=self.chat_model, latency_ms=5)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


def _fridge_json(text: str) -> str:
    return json.dumps({"lines": [{"speaker": "냉장고 회장", "text": text}], "reaction": "흠흠…"}, ensure_ascii=False)


async def _generate(fake: LLMProvider, monkeypatch, turn: int = 7):
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    project = get_project("fridge", SCENARIO)
    return await story_turn_service._generate(project, turn, "민트", [], "오늘 밤엔 문 안 열어요.", None, [])


async def test_violation_log_has_codes_and_counts_without_text(monkeypatch, caplog):
    secret = "흠흠. 비밀대사하나. 비밀대사둘. 비밀대사셋."
    fake = FakeGemini([_fridge_json(secret), _fridge_json(secret)])
    caplog.set_level("WARNING", logger="app.services.story_turn_service")
    with pytest.raises(story_turn_service.LLMError):
        await _generate(fake, monkeypatch)
    assert "codes=too_many_sentences sentences=4" in caplog.text
    assert "비밀대사" not in caplog.text
    # 두 번째 생성의 교정 메모에는 숫자만 들어간다.
    correction = " ".join(m["content"] for m in fake.kwargs[1]["messages"])
    assert "문장이 4개였다" in correction and "비밀대사" not in correction


async def test_correction_retry_still_succeeds_after_violation(monkeypatch):
    fake = FakeGemini([_fridge_json("흠흠. 첫째 문장. 둘째 문장. 셋째 문장."), _fridge_json("…자네가 나를? 흠흠. 그럼 부탁하지.")])
    reply = await _generate(fake, monkeypatch)
    assert reply.attempts == 2 and reply.violations == ["too_many_sentences"]


# --- 지문 표기 정규화 ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("[디ス플레이: 의기양양]\n좋은 태도일세.", "[디스플레이: 의기양양]\n좋은 태도일세."),  # 관측된 오염
        ("[디ｽ플레이: 의기양양] 좋은 태도일세.", "[디스플레이: 의기양양] 좋은 태도일세."),  # 반각 가타카나
        ("[디스플레이：의기양양] 좋네.", "[디스플레이: 의기양양] 좋네."),  # 전각 콜론
        ("[디스플레이 :  의기양양 ] 좋네.", "[디스플레이: 의기양양] 좋네."),  # 공백 차이
    ],
)
def test_display_variants_are_normalized(raw, expected):
    text, changed = normalize_display_tag(raw)
    assert changed and text == expected
    assert FRONTEND_DISPLAY.match(text).group(1) == "의기양양"


@pytest.mark.parametrize(
    "raw",
    [
        "[디스플레이: 의기양양]\n좋은 태도일세.",  # 이미 표준형
        "좋은 태도일세. [디ス플레이: 의기양양]",  # 맨 앞이 아님
        "[메모: 의기양양] 좋네.",  # 다른 대괄호
        "[디자인: 새 로고] 좋네.",
        "[디스크레이: 오타] 좋네.",  # 관측되지 않은 다른 글자
        "[디ス플레이: 줄\n바꿈] 좋네.",
        "흠흠. 이제야 말이 통하는군.",
    ],
)
def test_other_text_is_not_changed(raw):
    assert normalize_display_tag(raw) == (raw, False)


def test_parser_normalizes_contaminated_display_for_fridge(caplog):
    caplog.set_level("INFO", logger="app.services.story_turn_service")
    project = get_project("fridge", SCENARIO)
    lines, _ = parse_story_output(project, _fridge_json("[디ス플레이: 의기양양]\n좋은 태도일세. 신입 시절의 나를 보는 것 같군."))
    assert lines[0].text.startswith("[디스플레이: 의기양양]")
    assert len(sentences(lines[0].text)) == 2  # 정규화 후 지문은 문장 수에서 빠진다
    assert "지문 표기 정규화: project=fridge count=1" in caplog.text and "의기양양" not in caplog.text


# --- 구조화 출력 스키마 ---

@pytest.mark.parametrize(("project_id", "speakers", "max_items"), [
    ("fridge", ["냉장고 회장"], 1),
    ("cloud", ["토토", "비비", "나나", "키키", "두두"], 3),
])
def test_schema_shape_per_project(project_id, speakers, max_items):
    schema = story_response_schema(get_project(project_id, SCENARIO))
    lines = schema["properties"]["lines"]
    assert schema["type"] == "object" and schema["required"] == ["lines"]
    assert lines["type"] == "array" and lines["minItems"] == 1 and lines["maxItems"] == max_items
    assert lines["items"]["required"] == ["speaker", "text"]
    assert lines["items"]["properties"]["speaker"]["enum"] == speakers
    json.dumps(schema)  # 직렬화 가능


async def _gemini_request(json_schema=None, json_mode=True):
    captured: list[httpx.Request] = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]})

    provider = GeminiProvider(api_key="k", base_url="https://gemini.test/v1beta", chat_model="m",
                              embedding_model="e", timeout=1, embedding_dim=4, http_attempts=1)
    await provider.close()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.generate([{"role": "user", "content": "x"}], json_mode=json_mode, json_schema=json_schema)
    finally:
        await provider.close()
    return json.loads(captured[0].content)["generationConfig"]


async def test_gemini_request_body_includes_json_schema():
    schema = story_response_schema(get_project("fridge", SCENARIO))
    config = await _gemini_request(schema)
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == schema
    assert "responseSchema" not in config  # 구형 필드와 함께 보내지 않는다


async def test_gemini_request_body_without_schema_is_unchanged():
    config = await _gemini_request()
    assert config["responseMimeType"] == "application/json"
    assert "responseJsonSchema" not in config and "responseSchema" not in config
    plain = await _gemini_request(json_mode=False)
    assert "responseMimeType" not in plain


async def test_schema_passed_only_when_supported_and_enabled(monkeypatch):
    ok = _fridge_json("…자네가 나를? 흠흠. 그럼 부탁하지.")
    fake = FakeGemini([ok])
    await _generate(fake, monkeypatch)
    assert fake.kwargs[0]["json_schema"] == story_response_schema(get_project("fridge", SCENARIO))

    disabled = FakeGemini([ok])
    monkeypatch.setattr(settings, "story_response_schema", False)
    await _generate(disabled, monkeypatch)
    assert disabled.kwargs[0]["json_schema"] is None


async def test_provider_without_schema_support_gets_original_call(monkeypatch):
    calls: list[dict] = []

    class Legacy(LLMProvider):
        name = "gemini"
        chat_model = "legacy"

        async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
            calls.append({"json_mode": json_mode})
            return LLMResult(text=_fridge_json("…자네가 나를? 흠흠. 그럼 부탁하지."), provider="gemini", model="legacy", latency_ms=1)

        async def embed(self, texts):
            return []

        async def stream(self, messages, *, temperature=None, max_tokens=None):
            yield ""

    await _generate(Legacy(), monkeypatch)
    assert calls == [{"json_mode": True}]


def test_parser_and_controls_still_apply_to_schema_shaped_output():
    """스키마 형태로 와도 기존 파서·응답 제어가 그대로 검사한다."""
    project = get_project("fridge", SCENARIO)
    lines, _ = parse_story_output(project, _fridge_json("흠흠. 첫째 문장. 둘째 문장. 셋째 문장."))
    found = validate_lines(project, 7, [(l.speaker, l.text) for l in lines], [], "민트")
    assert "too_many_sentences" in [v.code for v in found]
    with pytest.raises(ValueError):
        parse_story_output(project, json.dumps({"lines": ["문자열 대사"]}, ensure_ascii=False))
    messages, _ = build_story_messages(project, "민트", 7, [], "x", None)
    assert "짧은 감탄도 한 문장으로 센다" in messages[0]["content"]
