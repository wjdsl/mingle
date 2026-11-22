"""선택지 문구의 {{user}} 호칭 자리표시 처리 테스트 (외부 API 없음).

- 서버 검증: 선택지 ID + 장면 데이터 원문 문구 정확 일치(변경 없음).
- 검증 통과 후에만 safe_nickname() 기준 호칭으로 채워 LLM 입력·저장 대화에 쓴다.
- 자유 입력은 그대로 둔다.
"""

from __future__ import annotations

import json
import re

import pytest

from app.services import story_turn_service
from app.services.llm.base import LLMProvider, LLMResult
from app.services.story_scenes import get_project

SCENARIO = "scenario_draft_v1"
PLACEHOLDER = re.compile(r"\{\{user\}\}|\[(호칭|닉네임)\]|\{nickname\}")


class RecordingGemini(LLMProvider):
    name = "gemini"
    chat_model = "fake-gemini-model"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.texts = ["흠흠. 이제야 말이 통하는군.", "그래야지. 달걀은 꼭 챙겨 먹게."]

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
        self.calls.append(messages)
        text = self.texts[min(len(self.calls), len(self.texts)) - 1]
        body = json.dumps({"lines": [{"speaker": "냉장고 회장", "text": text}], "reaction": "흠흠…"}, ensure_ascii=False)
        return LLMResult(text=body, provider=self.name, model=self.chat_model, latency_ms=3)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


def _first_choice():
    return get_project("fridge", SCENARIO).scenes[0].choices[0]


async def _start(client, monkeypatch, name: str = "민트"):
    fake = RecordingGemini()
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    session = await client.post("/api/sessions", json={"display_name": name})
    headers = {"X-Personal-Code": session.json()["personal_code"]}
    created = await client.post("/api/story-chat/conversations", json={"project": "fridge", "scene_set": SCENARIO}, headers=headers)
    assert created.status_code == 201, created.text
    return fake, headers, f"/api/story-chat/conversations/{created.json()['conversation_id']}/turns"


def _payload(turn: int, text: str, choice_id: str | None = None) -> dict:
    body: dict = {"request_id": f"req-{turn:02d}-nick01", "turn": turn, "input": {"text": text}}
    if choice_id:
        body["input"]["choice_id"] = choice_id
    return body


def _user_input(messages: list[dict[str, str]]) -> str:
    return json.loads(messages[-1]["content"])["사용자 입력"]


def test_only_fridge_first_choice_has_placeholder():
    found = {
        (pid, sset, turn)
        for sset in ("scenario_draft_v1", "ui_mock_v1")
        for pid in ("fridge", "cloud")
        for turn, scene in enumerate(get_project(pid, sset).scenes)
        if any(PLACEHOLDER.search(c.label) for c in scene.choices)
    }
    assert found == {("fridge", SCENARIO, 0)}
    assert _first_choice().label == "(문을 닫으며) 죄송해요. 제 이름은 {{user}}입니다."  # 원본 데이터 유지


async def test_validated_choice_is_filled_for_llm_and_history(client, monkeypatch):
    fake, headers, url = await _start(client, monkeypatch)
    choice = _first_choice()
    ok = await client.post(url, json=_payload(0, choice.label, choice.id), headers=headers)
    assert ok.status_code == 200, ok.text
    first = fake.calls[0]
    assert _user_input(first) == "(문을 닫으며) 죄송해요. 제 이름은 민트입니다."
    assert not PLACEHOLDER.search(first[0]["content"])  # 장면 카드의 선택지 목록도 채워진다
    assert '버튼 "(문을 닫으며) 죄송해요. 제 이름은 민트입니다."' in first[0]["content"]

    nxt = await client.post(url, json=_payload(1, "왜 냉장고가 됐어요?"), headers=headers)
    assert nxt.status_code == 200, nxt.text
    past_user = json.loads(fake.calls[1][1]["content"])["사용자 입력"]  # 저장된 대화 → 이전 맥락
    assert past_user == "(문을 닫으며) 죄송해요. 제 이름은 민트입니다."


@pytest.mark.parametrize("name", ["민트", "민준"])  # 받침 없는 이름·있는 이름
async def test_choice_wording_reads_naturally_for_any_final_consonant(client, monkeypatch, name):
    fake, headers, url = await _start(client, monkeypatch, name=name)
    choice = _first_choice()
    ok = await client.post(url, json=_payload(0, choice.label, choice.id), headers=headers)
    assert ok.status_code == 200, ok.text
    assert _user_input(fake.calls[0]) == f"(문을 닫으며) 죄송해요. 제 이름은 {name}입니다."


async def test_display_label_is_still_rejected_by_exact_validation(client, monkeypatch):
    fake, headers, url = await _start(client, monkeypatch)
    choice = _first_choice()
    shown = choice.label.replace("{{user}}", "민트")
    rejected = await client.post(url, json=_payload(0, shown, choice.id), headers=headers)
    assert rejected.status_code == 422
    wrong_id = await client.post(url, json=_payload(0, choice.label, "fridge_t01_unknown"), headers=headers)
    assert wrong_id.status_code == 422
    assert fake.calls == []


async def test_server_fallback_nickname_is_used(client, monkeypatch):
    fake, headers, url = await _start(client, monkeypatch, name="[민트]")
    choice = _first_choice()
    ok = await client.post(url, json=_payload(0, choice.label, choice.id), headers=headers)
    assert ok.status_code == 200, ok.text
    fallback = get_project("fridge", SCENARIO).nickname_fallback
    assert _user_input(fake.calls[0]) == f"(문을 닫으며) 죄송해요. 제 이름은 {fallback}입니다."


async def test_free_text_is_kept_as_typed(client, monkeypatch):
    fake, headers, url = await _start(client, monkeypatch)
    ok = await client.post(url, json=_payload(0, "저는 {{user}}라고 불러 주세요"), headers=headers)
    assert ok.status_code == 200, ok.text
    assert _user_input(fake.calls[0]) == "저는 {{user}}라고 불러 주세요"
