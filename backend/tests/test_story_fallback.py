"""냉장고·구름섬 AI 실패 시 고정 대사 진행 테스트 (2026-11-22 팀 결정).

공급자 503·429·시간 초과·응답 검증 실패 모두 오류 대신 장면 고정 대사로 진행하고,
저장 provider는 "fallback", 사유 코드는 로그와 메시지 extra에만 남는지 확인한다. 외부 API는 호출하지 않는다.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import Message, StoryTurnRecord
from app.services import story_dialogue, story_turn_service
from app.services.llm import LLMError
from app.services.llm.base import LLMProvider, LLMResult
from app.services.llm.gemini_provider import GeminiHTTPError, GeminiQuotaError, GeminiTimeoutError
from app.services.story_fallback_lines import FREE_INPUT_FALLBACK
from app.services.story_response_control import validate_lines
from app.services.story_scene_sets import MOCK_FREE_REPLY
from app.services.story_scenes import fill_user, get_project

SCENARIO = "scenario_draft_v1"
LOGGER = "app.services.story_turn_service"


class FailingGemini(LLMProvider):
    """항상 같은 결과(예외 또는 문자열)를 돌려주는 가짜 Gemini."""

    name = "gemini"
    chat_model = "fake-gemini-model"

    def __init__(self, outcome: Exception | str) -> None:
        self.outcome = outcome
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return LLMResult(text=self.outcome, provider=self.name, model=self.chat_model, latency_ms=1)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


async def start(client, project: str, name: str = "민트"):
    session = await client.post("/api/sessions", json={"display_name": name})
    headers = {"X-Personal-Code": session.json()["personal_code"], "X-Story-Provider": "gemini"}
    created = await client.post("/api/story-chat/conversations", json={"project": project, "scene_set": SCENARIO}, headers=headers)
    assert created.status_code == 201, created.text
    return headers, created.json()["conversation_id"], get_project(project, SCENARIO)


def payload(turn: int, text: str, choice_id: str | None = None, rid: str | None = None) -> dict:
    body: dict = {"request_id": rid or f"fb-{turn:02d}-abcdef", "turn": turn, "input": {"text": text}}
    if choice_id:
        body["input"]["choice_id"] = choice_id
    return body


def expected_free(project_id: str, turn: int, name: str = "민트") -> list[dict]:
    project = get_project(project_id, SCENARIO)
    return [
        {"speaker": speaker or project.speakers[0], "text": fill_user(text, name)}
        for speaker, text in FREE_INPUT_FALLBACK[project_id][turn + 1]
    ]


async def stored(conversation_id: str, turn: int) -> tuple[StoryTurnRecord, Message]:
    async with SessionLocal() as db:
        record = (
            await db.execute(
                select(StoryTurnRecord).where(
                    StoryTurnRecord.conversation_id == conversation_id, StoryTurnRecord.turn_index == turn
                )
            )
        ).scalar_one()
        message = await db.get(Message, record.assistant_message_id)
        return record, message


@pytest.mark.parametrize(
    "error, reason",
    [
        (GeminiHTTPError(503), "provider_http_503"),
        (GeminiQuotaError("minute", 30), "provider_quota_minute"),
        (GeminiTimeoutError("Gemini 응답 시간 초과"), "provider_timeout"),
        (LLMError("Gemini 연결 실패"), "provider_connection"),
    ],
    ids=["503", "429", "timeout", "connection"],
)
async def test_provider_failure_free_input_uses_scene_fixed_line(client, monkeypatch, caplog, error, reason):
    fake = FailingGemini(error)
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, _ = await start(client, "fridge")
    caplog.set_level("WARNING", logger=LOGGER)
    user_text = "비밀입력문장 저는 민트예요"
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=payload(0, user_text), headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["replies"] == expected_free("fridge", 0)
    assert (body["provider"], body["model"]) == ("fallback", "scene-fallback-v1")
    assert (body["completed_turns"], body["finished"], body["replayed"]) == (1, False, False)
    assert body["fallback_reason"] is None  # 사유 코드는 응답에 넣지 않는다(로그·저장 전용)

    record, message = await stored(cid, 0)
    assert record.provider == message.provider == "fallback"
    assert message.extra["story_fallback"] == {"reason": reason}
    assert message.extra["intent_id"] is None
    assert f"reason={reason}" in caplog.text and "input=free" in caplog.text
    assert "비밀입력문장" not in caplog.text and "좋네" not in caplog.text


async def test_validation_failure_uses_fixed_line_after_regeneration(client, monkeypatch, caplog):
    # 존댓말·성별 호칭 위반이 재생성 후에도 계속되면 '스토리 응답 검증 실패' → 고정 대사
    bad = json.dumps({"lines": [{"speaker": "냉장고 회장", "text": "이봐 총각, 알겠어요."}]}, ensure_ascii=False)
    fake = FailingGemini(bad)
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, _ = await start(client, "fridge")
    caplog.set_level("WARNING", logger=LOGGER)
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=payload(0, "안녕"), headers=headers)
    assert response.status_code == 200 and fake.calls == 2
    assert response.json()["replies"] == expected_free("fridge", 0)
    _, message = await stored(cid, 0)
    assert message.extra["story_fallback"]["reason"].startswith("response_control:")
    assert "총각" not in caplog.text


async def test_choice_uses_reference_reply_with_speaker_from_direction(client, monkeypatch):
    fake = FailingGemini(GeminiTimeoutError("timeout"))
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, project = await start(client, "cloud")
    url = f"/api/story-chat/conversations/{cid}/turns"
    assert (await client.post(url, json=payload(0, "민트"), headers=headers)).status_code == 200
    # 2턴 토토형 반응 방향: 토토가 기뻐함, 비비가 "먼저 안전수칙부터야." → 화자는 비비
    choice = project.scenes[1].choices[0]
    response = await client.post(url, json=payload(1, choice.label, choice.id), headers=headers)
    assert response.status_code == 200
    assert response.json()["replies"] == [{"speaker": "비비", "text": "먼저 안전수칙부터야."}]
    assert response.json()["provider"] == "fallback"


async def test_fridge_choice_keeps_display_direction_and_follow_up_lines(client, monkeypatch):
    fake = FailingGemini(GeminiHTTPError(503))
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, project = await start(client, "fridge")
    url = f"/api/story-chat/conversations/{cid}/turns"
    choice = project.scenes[0].choices[2]  # 고장·가전 취급: [디스플레이: 온도 -3℃ → -5℃] "플러그에 손대기만 해 보게!"
    first = await client.post(url, json=payload(0, choice.label, choice.id), headers=headers)
    assert first.json()["replies"][0]["text"] == "[디스플레이: 온도 -3℃ → -5℃]\n플러그에 손대기만 해 보게!"
    for turn in (1, 2):
        assert (await client.post(url, json=payload(turn, "음"), headers=headers)).status_code == 200
    # 4턴: 고정 대사 뒤에 장면 데이터의 두 번째 대사가 그대로 붙는다.
    fourth = (await client.post(url, json=payload(3, "아무것도 아니에요"), headers=headers)).json()
    assert fourth["replies"][0] == expected_free("fridge", 3)[0]
    assert len(fourth["replies"]) == 2 and "신제품 발표" in fourth["replies"][1]["text"]


async def test_choice_without_quoted_reply_uses_scene_free_line(client, monkeypatch):
    fake = FailingGemini(GeminiHTTPError(503))
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    project = get_project("cloud", SCENARIO)
    choice = next(c for c in project.scenes[6].choices if c.reference_reply == MOCK_FREE_REPLY)
    lines, reaction = story_turn_service.fallback_reply(project, project.scenes[6], 6, choice, "민트")
    assert [{"speaker": l.speaker, "text": l.text} for l in lines] == expected_free("cloud", 6)
    assert reaction == story_turn_service.DEFAULT_REACTION


async def test_fallback_replays_same_request_id_without_new_call(client, monkeypatch):
    fake = FailingGemini(GeminiHTTPError(503))
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, _ = await start(client, "cloud")
    url = f"/api/story-chat/conversations/{cid}/turns"
    body = payload(0, "구름", rid="same-request-0001")
    first = (await client.post(url, json=body, headers=headers)).json()
    calls = fake.calls
    again = (await client.post(url, json=body, headers=headers)).json()
    assert again["replayed"] is True and fake.calls == calls
    assert (again["replies"], again["provider"], again["model"]) == (first["replies"], "fallback", "scene-fallback-v1")
    messages = await client.get(f"/api/conversations/{cid}/messages?limit=50", headers=headers)
    assert len(messages.json()) == 2


async def test_crisis_input_is_unchanged_when_ai_is_failing(client, monkeypatch):
    fake = FailingGemini(GeminiHTTPError(503))
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, _ = await start(client, "fridge")
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=payload(0, "죽고 싶다"), headers=headers)
    assert response.json()["safety_notice"] is True and response.json()["completed_turns"] == 0
    assert fake.calls == 0


async def test_fallback_skips_fridge_qwen_rewrite(client, monkeypatch):
    class ExplodingQwen:
        async def generate(self, *args, **kwargs):  # 호출되면 안 된다
            raise AssertionError("Qwen called")

    monkeypatch.setattr(settings, "fridge_qwen_dialogue_enabled", True)
    monkeypatch.setattr(story_dialogue, "get_dialogue_llm", lambda: ExplodingQwen())
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: FailingGemini(GeminiHTTPError(503)))
    headers, cid, _ = await start(client, "fridge")
    body = (await client.post(f"/api/story-chat/conversations/{cid}/turns", json=payload(0, "안녕"), headers=headers)).json()
    assert body["provider"] == body["story_provider"] == body["dialogue_provider"] == "fallback"
    assert body["qwen_used"] is False


@pytest.mark.parametrize("project_id", ["fridge", "cloud"])
async def test_all_failing_ten_turns_reach_ending(client, monkeypatch, project_id):
    fake = FailingGemini(GeminiHTTPError(503))
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid, project = await start(client, project_id)
    for turn, scene in enumerate(project.scenes):
        if scene.input_mode == "none":
            response = await client.post(
                f"/api/story-chat/conversations/{cid}/fixed-turns",
                json={"request_id": f"fixed-{turn:02d}-abcdef", "turn": turn},
                headers=headers,
            )
            assert response.json()["provider"] == "fixed"
        else:
            body = payload(turn, scene.choices[0].label, scene.choices[0].id) if scene.choices and turn % 2 else payload(turn, "그렇구나")
            response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body, headers=headers)
            assert response.json()["provider"] == "fallback"
        assert response.status_code == 200, response.text
        texts = [r["text"] for r in response.json()["replies"]]
        assert texts and not any("[Mock]" in t or "{{user}}" in t for t in texts)
    final = response.json()
    assert final["finished"] is True and final["completed_turns"] == 10 and final["ending"]


@pytest.mark.parametrize("project_id", ["fridge", "cloud"])
def test_free_fallback_table_covers_input_scenes_and_passes_response_controls(project_id):
    project = get_project(project_id, SCENARIO)
    for turn, scene in enumerate(project.scenes):
        if scene.input_mode == "none":
            assert turn + 1 not in FREE_INPUT_FALLBACK[project_id]
            continue
        rows = FREE_INPUT_FALLBACK[project_id][turn + 1]
        assert 1 <= len(rows) <= project.max_lines
        lines = [(speaker or project.speakers[0], fill_user(text, "민트")) for speaker, text in rows]
        assert all(speaker in project.speakers for speaker, _ in lines)
        assert validate_lines(project, turn, lines, [], "민트") == [], (turn + 1, lines)


def test_fallback_reason_logger_is_kept_in_failure_log_file():
    from app.core.logging import FAILURE_LOGGERS

    assert LOGGER in FAILURE_LOGGERS
