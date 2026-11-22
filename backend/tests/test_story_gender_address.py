"""사용자 호칭 뒤 성별 호칭(군/양) 검사 테스트 (외부 API 없음).

하게체 어미 "~군"과 분량의 "양"은 위반이 아니어야 한다.
"""

from __future__ import annotations

import json

import pytest

from app.services import story_turn_service
from app.services.llm.base import LLMProvider, LLMResult
from app.services.story_prompt import build_story_messages
from app.services.story_response_control import validate_lines
from app.services.story_scenes import fill_user, get_project

SCENARIO = "scenario_draft_v1"


def _codes(text: str, nickname: str = "민준", project_id: str = "fridge", turn: int = 0) -> list[str]:
    project = get_project(project_id, SCENARIO)
    speaker = project.speakers[0]
    return [v.code for v in validate_lines(project, turn, [(speaker, text)], [], nickname)]


@pytest.mark.parametrize(
    ("text", "nickname"),
    [
        ("흠흠. 이제야 말이 통하는군, 민준 군.", "민준"),  # 실제 관측
        ("민준군! 문 닫게.", "민준"),
        ("고맙네, 민트 양, 문은 닫게.", "민트"),
        ("민트 양.", "민트"),
    ],
)
def test_gendered_suffix_after_nickname_is_rejected(text, nickname):
    assert "forbidden_address" in _codes(text, nickname)


@pytest.mark.parametrize(
    ("text", "nickname"),
    [
        ("흠흠. 이제야 말이 통하는군.", "민준"),  # 하게체 어미
        ("이제야 알아보는군. 문은 닫고 감동하게.", "민준"),
        ("민트 양이 많군.", "민트"),  # 분량의 '양'
        ("민준, 자네 생각은 어떤가?", "민준"),
        ("자네가 나를? 흠흠. 그럼 부탁하지.", "자네"),  # 대체 호칭
    ],
)
def test_normal_lines_are_not_rejected(text, nickname):
    assert "forbidden_address" not in _codes(text, nickname)


def test_existing_gender_words_still_rejected():
    assert "forbidden_address" in _codes("이봐 총각, 문 닫게.")
    assert "forbidden_address" in _codes("아가씨, 문 닫게.")


@pytest.mark.parametrize("project_id", ["fridge", "cloud"])
def test_scenario_lines_with_nickname_have_no_false_positive(project_id):
    project = get_project(project_id, SCENARIO)
    for turn, scene in enumerate(project.scenes):
        texts = [l.text for l in scene.opening_lines + scene.follow_up_lines + scene.closing_lines + scene.fixed_lines]
        texts += [c.reference_reply for c in scene.choices if c.reference_reply]
        texts += [it.response_direction for it in scene.intents]  # 예시 대사 포함
        for text in texts:
            filled = fill_user(text, "민준")
            found = [v for v in validate_lines(project, turn, [(project.speakers[0], filled)], [], "민준") if v.code == "forbidden_address"]
            assert not found, (project_id, turn)


def test_prompt_names_gendered_suffix_examples():
    project = get_project("fridge", SCENARIO)
    messages, _ = build_story_messages(project, "민준", 0, [], "x", None)
    assert "'민준 군', '민준 양', '총각', '아가씨'처럼 성별을 드러내는 호칭을 붙이지 않는다" in messages[0]["content"]


class TwoStepGemini(LLMProvider):
    name = "gemini"
    chat_model = "fake-gemini-model"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls: list[list[dict[str, str]]] = []

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
        self.calls.append(messages)
        text = self.texts[len(self.calls) - 1]
        body = json.dumps({"lines": [{"speaker": "냉장고 회장", "text": text}], "reaction": "만족"}, ensure_ascii=False)
        return LLMResult(text=body, provider=self.name, model=self.chat_model, latency_ms=1)

    async def embed(self, texts):
        return []

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


async def test_gendered_reply_is_corrected_once(monkeypatch, caplog):
    fake = TwoStepGemini(["흠흠. 이제야 말이 통하는군, 민준 군.", "흠흠. 이제야 말이 통하는군, 민준."])
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    caplog.set_level("WARNING", logger="app.services.story_turn_service")
    project = get_project("fridge", SCENARIO)
    reply = await story_turn_service._generate(project, 0, "민준", [], "x", None, [])
    assert reply.attempts == 2 and reply.violations == ["forbidden_address"]
    assert "성별을 가정하는 호칭을 썼다" in fake.calls[1][-1]["content"]
    assert "codes=forbidden_address" in caplog.text and "민준 군" not in caplog.text
