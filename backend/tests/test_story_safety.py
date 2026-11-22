"""냉장고·구름섬 위기 신호 처리 테스트: LLM 미호출, 장면 미진행, 입력 미저장."""

from __future__ import annotations

import pytest

from app.services import story_turn_service
from app.services.llm.base import LLMProvider
from app.services.story_safety import COMPANION_LINES, is_story_crisis
from app.services.story_scenes import CLOUD_SCENES, FRIDGE_SCENES



async def _start(client, project: str):
    session = await client.post("/api/sessions", json={"display_name": "민트"})
    assert session.status_code == 201, session.text
    headers = {"X-Personal-Code": session.json()["personal_code"]}
    created = await client.post("/api/story-chat/conversations", json={"project": project}, headers=headers)
    assert created.status_code == 201, created.text
    return headers, created.json()["conversation_id"]


def _turn(turn: int, text: str, choice_id: str | None = None, request_id: str | None = None) -> dict:
    payload: dict = {"request_id": request_id or f"req-{turn:02d}-abcdef", "turn": turn, "input": {"text": text}}
    if choice_id:
        payload["input"]["choice_id"] = choice_id
    return payload


async def _message_count(client, headers, conversation_id) -> int:
    response = await client.get(f"/api/conversations/{conversation_id}/messages?limit=200", headers=headers)
    assert response.status_code == 200, response.text
    return len(response.json())


class ExplodingLLM(LLMProvider):
    """호출되면 실패하는 공급자: 위기 입력이 LLM에 닿지 않음을 확인한다."""

    name = "gemini"
    chat_model = "must-not-be-called"

    async def generate(self, messages, **kwargs):
        raise AssertionError("위기 입력에서 LLM을 호출하면 안 된다")

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, **kwargs):
        yield ""


@pytest.mark.parametrize(
    "text",
    ["죽고 싶다", "죽고싶어요", "그냥 사라지고 싶어", "자해하고 싶다", "다 끝내고 싶다", "다 끝내고싶어", "살기 싫어", "자살", "살고 싶지 않아"],
)
def test_crisis_expressions_are_detected(text):
    assert is_story_crisis(text)


@pytest.mark.parametrize(
    "text",
    ["면접 또 떨어졌어요", "요즘 너무 지쳐요", "냉장고 문 열어도 돼요?", "오늘 일 끝내고 싶다", "", "아이스크림 먹고 싶어"],
)
def test_ordinary_hard_talk_is_not_crisis(text):
    assert not is_story_crisis(text)


@pytest.mark.parametrize("project,scenes", [("fridge", FRIDGE_SCENES), ("cloud", CLOUD_SCENES)])
async def test_crisis_input_returns_notice_without_llm_save_or_progress(client, monkeypatch, project, scenes):
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: ExplodingLLM())
    headers, cid = await _start(client, project)
    url = f"/api/story-chat/conversations/{cid}/turns"

    response = await client.post(url, json=_turn(0, "너무 힘들어서 죽고 싶어요"), headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["safety_notice"] is True
    assert body["provider"] == "safety"
    assert body["guardrail_triggered"] is False
    speaker, line = COMPANION_LINES[project]
    assert body["replies"] == [{"speaker": speaker, "text": line}]
    assert (body["turn"], body["completed_turns"], body["finished"]) == (0, 0, False)
    assert await _message_count(client, headers, cid) == 0  # 입력 원문도 저장하지 않는다
    state = await client.get(f"/api/story-chat/conversations/{cid}", headers=headers)
    assert state.json()["completed_turns"] == 0


async def test_story_continues_normally_after_crisis_notice(client, monkeypatch):
    headers, cid = await _start(client, "fridge")
    url = f"/api/story-chat/conversations/{cid}/turns"
    crisis = await client.post(url, json=_turn(0, "죽고 싶어", request_id="req-crisis-0001"), headers=headers)
    assert crisis.json()["safety_notice"] is True

    choice = FRIDGE_SCENES[0].choices[0]
    resumed = await client.post(url, json=_turn(0, choice.label, choice.id, request_id="req-resume-0001"), headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["safety_notice"] is False
    assert resumed.json()["completed_turns"] == 1


async def test_crisis_notice_repeats_every_time(client):
    headers, cid = await _start(client, "cloud")
    url = f"/api/story-chat/conversations/{cid}/turns"
    for index in range(3):
        response = await client.post(url, json=_turn(0, "다 끝내고 싶어", request_id=f"req-crisis-{index:04d}"), headers=headers)
        assert response.json()["safety_notice"] is True
        assert response.json()["completed_turns"] == 0


async def test_choice_label_is_never_treated_as_crisis(client):
    headers, cid = await _start(client, "fridge")
    choice = FRIDGE_SCENES[0].choices[0]
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=_turn(0, choice.label, choice.id), headers=headers)
    assert response.json()["safety_notice"] is False
