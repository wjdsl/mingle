"""푸르마 10턴 장면형 스토리(/api/story-chat, puruma_draft_v1) 테스트.

- 기획서 원문 문장 대조, 프론트 Mock과의 문장 일치
- 상태 규칙(스탯·친밀도·반복 감쇠), 홍보 R1~R3 상한, 엔딩 판정 순서
- 서버 Mock 10턴 완주, 재시도 중복 방지, 위기 입력, AI 실패 시 고정 대사, 로컬 기억 왕복
외부 API는 호출하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Message, StoryTurnRecord
from app.services import puruma_state as ps
from app.services import story_turn_service
from app.services.llm.base import LLMProvider, LLMResult
from app.services.llm.gemini_provider import GeminiHTTPError
from app.services.project_stats import build_project_stats
from app.services.puruma_scenes import (
    BURNOUT_LINE,
    CC_SEED_LINE,
    CHOICES,
    NEAR_MISS_LINE,
    SOLO_RETURN_LINE,
    SOS,
    TRANSITIONS,
    TURNS,
    puruma_project,
)
from app.services.story_response_control import validate_lines
from app.services.story_scenes import get_project

ROOT = Path(__file__).resolve().parents[2]
PLAN = (ROOT / "docs" / "푸르마_프로젝트_기획서.md").read_text(encoding="utf-8")
FRONT_SCENES = ROOT / "frontend" / "src" / "projects" / "puruma" / "scenes.ts"
SET = "puruma_draft_v1"


class ScriptedLLM(LLMProvider):
    name = "gemini"
    chat_model = "fake-gemini-model"

    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, str]]] = []

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False, **_):
        self.calls.append(messages)
        item = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(item, Exception):
            raise item
        return LLMResult(text=item, provider=self.name, model=self.chat_model, latency_ms=2)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


def reply_json(text: str, **extra) -> str:
    return json.dumps({"lines": [{"speaker": "푸르마", "text": text}], "reaction": "히히힝!", **extra}, ensure_ascii=False)


async def start(client, name: str = "민트", provider: str = "mock"):
    session = await client.post("/api/sessions", json={"display_name": name})
    headers = {"X-Personal-Code": session.json()["personal_code"], "X-Story-Provider": provider}
    created = await client.post("/api/story-chat/conversations", json={"project": "puruma"}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["scene_set"] == SET and created.json()["total_turns"] == 10
    return headers, created.json()["conversation_id"]


def body(turn: int, text: str, choice_id: str | None = None, notes: list | None = None, rid: str | None = None) -> dict:
    data: dict = {"request_id": rid or f"pu-{turn:02d}-abcdef", "turn": turn, "input": {"text": text}}
    if choice_id:
        data["input"]["choice_id"] = choice_id
    if notes is not None:
        data["notes"] = notes
    return data


def choose(turn: int, choice_id: str, notes: list | None = None, rid: str | None = None) -> dict:
    return body(turn, CHOICES[choice_id].label, choice_id, notes, rid)


# --------------------------------------------------------------------------- #
# 문장 출처
# --------------------------------------------------------------------------- #
def test_plan_sentences_are_verbatim_from_planning_doc():
    for text in [*SOS.values(), *TRANSITIONS.values()]:
        assert text in PLAN, text
    for spec in TURNS:
        for choice in spec.choices:
            if choice.src == "plan":
                assert f"| {choice.label} |" in PLAN, choice.label
            if choice.reply_src == "plan":
                assert choice.reply in PLAN, choice.reply
    # 초안 대사 안의 기획서 인용
    for quote in ("선배랑 같이 먹을 걸 그랬어요", "말이 먹어도 되는 걸까요?", "이 시간이 오래갔으면 좋겠어요", "한 학기 위시리스트에 넣었어요!",
                  "저도 그쪽이 궁금했어요. 같이 알아봐요.", "한 걸음만 더 갔으면 됐는데", "그거 어디 가면 볼 수 있어요?"):
        assert quote in PLAN, quote
    assert "선배랑 같이 먹을 걸 그랬어요" in SOLO_RETURN_LINE and "한 걸음만 더 갔으면 됐는데" in NEAR_MISS_LINE


def test_frontend_mock_uses_same_openings_and_choices():
    front = FRONT_SCENES.read_text(encoding="utf-8")
    for spec in TURNS:
        for line in spec.opening.split("\n"):
            assert json.dumps(line, ensure_ascii=False)[1:-1] in front, line
        for choice in spec.choices:
            assert f"'{choice.id}'" in front and choice.label in front and choice.reply in front, choice.id


def test_scene_set_is_separate_from_other_projects():
    assert get_project("puruma", SET) is puruma_project()
    assert get_project("puruma") is None and get_project("puruma", "scenario_draft_v1") is None
    assert get_project("fridge", SET) is None
    assert len(puruma_project().scenes) == 10


# --------------------------------------------------------------------------- #
# 상태 규칙
# --------------------------------------------------------------------------- #
def test_button_free_sos_and_caps():
    state = ps.apply_turn(ps.PurumaState(), ps.TurnView(0, "c1_t1_a"))  # SOS 버튼: 탐구 +6, 친밀도 +2+5 → 상한 5
    assert state.stats["탐구"] == 6 and state.affinity == 15
    state = ps.apply_turn(state, ps.TurnView(1, None, "topic_study", "응원·도움"))  # 자유 입력: +3, 태도 +3
    assert state.stats["탐구"] == 9 and state.affinity == 18
    state = ps.apply_turn(state, ps.TurnView(2, "c2_t3_c"))  # 탐구 3턴 연속 → +1
    assert state.stats["탐구"] == 10
    state = ps.apply_turn(state, ps.TurnView(3, None, "topic_daily", "퉁명·부정"))  # 일상 0, 친밀도 -1
    assert state.stats["탐구"] == 10 and state.affinity == 22
    assert ps.apply_turn(ps.PurumaState(affinity=0), ps.TurnView(1, None, None, "퉁명·부정")).affinity == 0
    # 분류가 없으면(Mock·AI 실패) 일상·중립
    assert ps.apply_turn(ps.PurumaState(), ps.TurnView(1, None)).affinity == 11


def views(*choices: str) -> list[ps.TurnView]:
    return [ps.TurnView(t, c) for t, c in enumerate(choices)]


def test_endings_follow_planning_order():
    social = views("c1_t1_b", "c1_t2_a", "c2_t3_b", "c2_t4_c", "c3_t5_b", "c3_t6_a", "c4_t7_a", "c4_t8_a", "c5_t9_b", "c6_t10_a")
    assert ps.judge(ps.fold(social)) == "career_prep_pruma"
    cc = [*social[:6], ps.TurnView(6, "c4_t7_c"), *social[7:]]
    assert ps.fold(cc).cc == "cc_seed" and ps.judge(ps.fold(cc)) == "cc_pruma"  # 히든이 홍보보다 먼저
    study = views("c1_t1_a", "c1_t2_a", "c2_t3_c", "c2_t4_c", "c3_t5_a", "c3_t6_a", "c4_t7_c", "c4_t8_a", "c5_t9_a", "c6_t10_b")
    low = [ps.TurnView(t, c) for t, c in enumerate(["c1_t1_a", "c1_t2_a", "c2_t3_c", "c2_t4_c", "c3_t5_a", "c3_t6_a"])]
    # 탐구만 18 이상, 나머지 6 이하 → 휴학 (CC 분기가 없도록 7턴은 공연)
    leave = [*low, ps.TurnView(6, "c4_t7_a"), ps.TurnView(7, "c4_t8_a"), ps.TurnView(8, "c5_t9_a"), ps.TurnView(9, "c6_t10_b")]
    state = ps.fold(leave)
    assert state.stats["예술"] == 6 and state.stats["글로벌"] == 6
    assert ps.judge(state) == "leave_pruma"
    # 탐구 18 + 5턴 도서관 + 다른 스탯도 올림 → 도서관 지박령
    library = [ps.TurnView(t, c) for t, c in enumerate(["c1_t1_a", "c1_t2_a", "c2_t3_b", "c2_t4_c", "c3_t5_a", "c3_t6_a", "c4_t7_b", "c4_t8_a", "c5_t9_a", "c6_t10_d"])]
    state = ps.fold(library)
    assert state.stats["탐구"] == 18 and ps.judge(state) == "library_ghost_pruma"
    # 교환학생 선택 + 글로벌 6
    exchange = [ps.TurnView(t, c) for t, c in enumerate(["c1_t1_b", "c1_t2_a", "c2_t3_d", "c2_t4_c", "c3_t5_c", "c3_t6_a", "c4_t7_a", "c4_t8_a", "c5_t9_c", "c6_t10_b"])]
    assert ps.judge(ps.fold(exchange)) == "exchange_pruma"
    # 취업을 골랐지만 소통이 모자람 → 종강 생존 + 재도전 한마디
    short = [ps.TurnView(t, c) for t, c in enumerate(["c1_t1_a", "c1_t2_a", "c2_t3_d", "c2_t4_c", "c3_t5_c", "c3_t6_a", "c4_t7_a", "c4_t8_a", "c5_t9_c", "c6_t10_a"])]
    assert ps.judge(ps.fold(short)) == "survivor_pruma" and ps.near_miss(ps.fold(short))
    assert ps.judge(ps.fold([])) == "survivor_pruma" and not ps.near_miss(ps.fold([]))
    assert study  # 사용하지 않는 시나리오도 형식 확인


def test_cc_branch_uses_affinity_before_festival_choice():
    assert ps.apply_turn(ps.PurumaState(affinity=24), ps.TurnView(6, "c4_t7_c")).cc == "solo_return"
    assert ps.apply_turn(ps.PurumaState(affinity=25), ps.TurnView(6, "c4_t7_c")).cc == "cc_seed"
    assert ps.appended_lines(ps.PurumaState(affinity=30), 6, "c4_t7_c", None) == [CC_SEED_LINE]
    assert ps.appended_lines(ps.PurumaState(affinity=10), 6, "c4_t7_c", None) == [SOLO_RETURN_LINE]


def test_promo_rules_r1_r3_and_limits():
    empty = ps.PurumaState()
    assert ps.select_promo(empty, 0, "c1_t1_a", "") is None  # 개강: 홍보 없음
    assert ps.select_promo(empty, 6, None, "동아리 가자") is None  # 축제: 홍보 없음
    assert ps.select_promo(empty, 8, None, "도서관 가자") is None  # 기말: 홍보 없음
    assert ps.select_promo(empty, 2, "c2_t3_a", "").id == "rag_dining_cafeteria_menu"
    assert ps.select_promo(empty, 2, "c2_t3_c", "") is None  # 2구간에서 도서관은 쓰지 않음
    assert ps.select_promo(empty, 2, None, "학식 먹으러 가자").id == "rag_dining_cafeteria_menu"
    assert ps.select_promo(empty, 2, None, "도서관 좋아") is None
    shown = ps.PurumaState(promos=[(2, "rag_dining_cafeteria_menu")])
    assert ps.select_promo(shown, 3, "c2_t4_a", "") is None  # 같은 콘텐츠는 다시 보이지 않음
    assert ps.select_promo(shown, 3, "c2_t4_b", "").id == "rag_clubs_yu_general_union"
    full = ps.PurumaState(promos=[(2, "rag_dining_cafeteria_menu"), (3, "rag_clubs_yu_general_union")])
    assert ps.select_promo(full, 3, None, "동아리") is None  # 구간당 2개
    assert ps.select_promo(empty, 5, None, "시험이 걱정돼").id == "rag_library_central"  # R2 조기 노출
    for choice_id, promo_id in (("c6_t10_a", "rag_career_center"), ("c6_t10_b", "rag_international_office"),
                                ("c6_t10_c", "rag_student_life_yutopia"), ("c6_t10_d", "rag_startup_incubation")):
        promo = ps.select_promo(empty, 9, choice_id, "")
        assert promo.id == promo_id and promo.url.startswith("https://")
    assert ps.path_for(9, None, ps.select_promo(empty, 9, None, "교환학생 가 볼래"), "교환학생 가 볼래") == "exchange"


def test_recall_once_per_section_and_burnout_hint():
    assert ps.RECALL_TURNS == frozenset({1, 3, 5, 7, 8, 9})
    burnout = ps.fold(views("c1_t1_a", "c1_t2_a", "c2_t3_c", "c2_t4_c", "c3_t5_a"))
    assert ps.appended_lines(burnout, 5, "c3_t6_a", ps.apply_turn(burnout, ps.TurnView(5, "c3_t6_a"))) == [BURNOUT_LINE]
    mixed = ps.fold(views("c1_t1_b", "c1_t2_a", "c2_t3_b", "c2_t4_c", "c3_t5_b"))
    assert ps.appended_lines(mixed, 5, "c3_t6_a", ps.apply_turn(mixed, ps.TurnView(5, "c3_t6_a"))) == []


def test_response_control_allows_polite_and_ai_honesty_but_not_urls():
    project = puruma_project()
    assert validate_lines(project, 0, [("푸르마", "저는 인공지능이 연기하는 캐릭터예요. 그래도 같이 찾아봐요!")], [], "선배") == []
    codes = [v.code for v in validate_lines(project, 2, [("푸르마", "학식은 www.yu.ac.kr 에서 볼 수 있어요!")], [], "선배")]
    assert codes == ["url"]


# --------------------------------------------------------------------------- #
# API (서버 Mock)
# --------------------------------------------------------------------------- #
CAREER_ROUTE = ["c1_t1_b", "c1_t2_a", "c2_t3_a", "c2_t4_b", "c3_t5_b", "c3_t6_a", "c4_t7_a", "c4_t8_b", "c5_t9_b", "c6_t10_a"]


async def test_server_mock_full_run_with_promos_notes_and_ending(client):
    headers, cid = await start(client)
    notes: list = []
    promos = []
    for turn, choice_id in enumerate(CAREER_ROUTE):
        response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(turn, choice_id, notes), headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["provider"] == "mock" and data["replies"][0]["speaker"] == "푸르마"
        assert data["replies"][0]["text"] == CHOICES[choice_id].reply
        assert data["emotion"] == CHOICES[choice_id].emotion
        notes = data["notes"]
        promos.append(data["promo"]["id"] if data["promo"] else None)
    assert promos == [None, None, "rag_dining_cafeteria_menu", "rag_clubs_yu_general_union", "rag_library_central",
                      None, None, None, None, "rag_career_center"]
    assert data["finished"] and data["ending"] == "career_prep_pruma"
    assert any(n["field"] == "section_choice" for n in notes) and len(notes) <= 10
    progress = await client.get(f"/api/story-chat/conversations/{cid}", headers=headers)
    assert progress.json()["ending"] == "career_prep_pruma" and progress.json()["finished"]
    again = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(9, "c6_t10_a", rid="pu-late-abcdef"), headers=headers)
    assert again.status_code == 409


async def test_replay_returns_same_payload_without_double_counting(client):
    headers, cid = await start(client)
    for turn, choice_id in enumerate(CAREER_ROUTE[:2]):
        await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(turn, choice_id), headers=headers)
    first = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(2, "c2_t3_a", []), headers=headers)
    replay = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(2, "c2_t3_a", []), headers=headers)
    assert replay.json()["replayed"] and replay.json()["promo"] == first.json()["promo"]
    assert replay.json()["notes"] == first.json()["notes"] and replay.json()["emotion"] == first.json()["emotion"]
    async with SessionLocal() as db:
        state = ps.fold(await ps.load_views(db, cid))
    assert len(state.promos) == 1 and state.stats["소통"] == 6


async def test_crisis_input_is_not_progress_stat_or_memory(client):
    headers, cid = await start(client)
    notes = [{"key": "interest:그림", "field": "interest", "value": "그림", "importance": "medium", "created_at_turn": 1, "updated_at_turn": 1}]
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body(0, "요즘 죽고 싶어", notes=notes), headers=headers)
    data = response.json()
    assert data["safety_notice"] and data["completed_turns"] == 0 and data["promo"] is None
    assert data["notes"] == notes and data["replies"][0]["speaker"] == "푸르마"
    async with SessionLocal() as db:
        count = len((await db.execute(select(StoryTurnRecord).where(StoryTurnRecord.conversation_id == cid))).scalars().all())
    assert count == 0


async def test_ai_failure_uses_fixed_lines_and_records_fallback(client, monkeypatch):
    fake = ScriptedLLM([GeminiHTTPError(503)])
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid = await start(client, provider="gemini")
    choice = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(0, "c1_t1_a"), headers=headers)
    assert choice.json()["provider"] == "fallback" and choice.json()["replies"][0]["text"] == CHOICES["c1_t1_a"].reply
    free = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body(1, "조용히 들어가 볼까?"), headers=headers)
    assert free.json()["provider"] == "fallback" and free.json()["replies"][0]["text"] == TURNS[1].free_reply
    assert free.json()["emotion"] == TURNS[1].free_emotion


async def test_llm_classification_feeds_state_and_context(client, monkeypatch):
    fake = ScriptedLLM([
        reply_json("선배, 물어보는 건 좀 떨리지만 해 볼게요!", emotion="confused"),
        reply_json("살금살금 들어가 볼게요. 또각, 앗!", emotion="happy"),
        reply_json("우와, 학식이요? 선배가 추천하면 꼭 먹어 볼래요!", emotion="sparkle", intent_id="topic_daily", attitude="응원·도움"),
    ])
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid = await start(client, provider="gemini")
    for turn, choice_id in enumerate(CAREER_ROUTE[:2]):
        await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(turn, choice_id), headers=headers)
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body(2, "점심엔 학식 먹어 봐"), headers=headers)
    data = response.json()
    assert data["provider"] == "gemini" and data["emotion"] == "sparkle"
    assert data["promo"]["id"] == "rag_dining_cafeteria_menu"
    system = fake.calls[-1][0]["content"]
    assert "링크 카드를 붙인다" in system and "선배" in system and "말투 단계: 어색" in system
    async with SessionLocal() as db:
        record = (await db.execute(select(StoryTurnRecord).where(StoryTurnRecord.conversation_id == cid, StoryTurnRecord.turn_index == 2))).scalar_one()
        extra = (await db.get(Message, record.assistant_message_id)).extra["puruma"]
    assert extra["topic"] == "topic_daily" and extra["attitude"] == "응원·도움"


async def test_url_in_reply_is_corrected_once(client, monkeypatch):
    fake = ScriptedLLM([reply_json("www.yu.ac.kr 에 있어요!"), reply_json("지도에 이렇게 나오는 거였구나! 선배 최고예요.")])
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    headers, cid = await start(client, provider="gemini")
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(0, "c1_t1_a"), headers=headers)
    assert response.json()["provider"] == "gemini" and "www" not in response.json()["replies"][0]["text"]
    assert len(fake.calls) == 2


async def test_cc_seed_line_is_appended_after_festival_choice(client):
    headers, cid = await start(client)
    for turn, choice_id in enumerate(CAREER_ROUTE[:6]):
        await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(turn, choice_id), headers=headers)
    response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(6, "c4_t7_c"), headers=headers)
    texts = [r["text"] for r in response.json()["replies"]]
    assert texts == [CHOICES["c4_t7_c"].reply, CC_SEED_LINE]


async def test_notes_are_rejected_for_other_projects_and_fridge_shape_unchanged(client):
    session = await client.post("/api/sessions", json={"display_name": "민트"})
    headers = {"X-Personal-Code": session.json()["personal_code"]}
    created = await client.post("/api/story-chat/conversations", json={"project": "fridge"}, headers=headers)
    assert created.json()["scene_set"] == "ui_mock_v1"
    cid = created.json()["conversation_id"]
    rejected = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body(0, "안녕하세요", notes=[]), headers=headers)
    assert rejected.status_code == 422
    ok = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body(0, "안녕하세요"), headers=headers)
    assert "emotion" not in ok.json() and "promo" not in ok.json()
    mismatch = await client.post("/api/story-chat/conversations", json={"project": "puruma", "scene_set": "ui_mock_v1"}, headers=headers)
    assert mismatch.status_code == 422


async def test_project_stats_count_puruma_story_turns(client):
    async with SessionLocal() as db:
        before = await build_project_stats(db, "puruma", 1)
    headers, cid = await start(client)
    for turn, choice_id in enumerate(CAREER_ROUTE[:3]):
        await client.post(f"/api/story-chat/conversations/{cid}/turns", json=choose(turn, choice_id), headers=headers)
    async with SessionLocal() as db:
        after = await build_project_stats(db, "puruma", 1)
    assert after.chat.conversations == before.chat.conversations + 1
    assert after.chat.turns == before.chat.turns + 3


@pytest.mark.parametrize("turn", range(10))
def test_every_scene_has_fallback_and_prompt(turn):
    from app.services.story_prompt import build_story_messages

    project = puruma_project()
    scene = project.scenes[turn]
    assert scene.default_reply and scene.choices
    messages, _ = build_story_messages(project, "선배", turn, [], "안녕", None, None, "## 현재 진행 상태")
    assert "## 현재 진행 상태" in messages[0]["content"] and "attitude" in messages[0]["content"]


def test_gemini_schema_carries_puruma_fields_only():
    from app.services.story_turn_service import story_response_schema

    props = story_response_schema(puruma_project())["properties"]
    assert props["emotion"]["enum"] == ["confused", "happy", "sparkle"]
    assert props["attitude"]["enum"] == ["응원·도움", "중립", "퉁명·부정"]
    assert props["intent_id"]["enum"][0] == "topic_study" and "topic_daily" in props["intent_id"]["enum"]
    assert story_response_schema(puruma_project())["required"] == ["lines", "emotion", "intent_id", "attitude"]
    fridge_schema = story_response_schema(get_project("fridge"))
    fridge = fridge_schema["properties"]
    assert "emotion" not in fridge and "attitude" not in fridge and fridge["intent_id"] == {"type": "string"}
    assert fridge_schema["required"] == ["lines"]


def test_free_input_career_path_counts_like_button():
    base = [ps.TurnView(t, c) for t, c in enumerate(["c1_t1_a", "c1_t2_a", "c2_t3_d", "c2_t4_c", "c3_t5_c", "c3_t6_a", "c4_t7_a", "c4_t8_a", "c5_t9_c"])]
    by_button = ps.fold([*base, ps.TurnView(9, "c6_t10_b")])
    by_text = ps.fold([*base, ps.TurnView(9, None, "topic_global", "응원·도움", "rag_international_office", "exchange")])
    assert by_text.stats["글로벌"] == by_button.stats["글로벌"] == 6
    assert ps.judge(by_text) == ps.judge(by_button) == "exchange_pruma"
    # 진로를 못 정한 자유 입력은 기존처럼 주제 +3
    vague = ps.fold([*base, ps.TurnView(9, None, "topic_global", "중립", None, None)])
    assert vague.stats["글로벌"] == 3 and vague.path is None
    # 자유 입력 진로도 조건이 모자라면 재도전 한마디가 붙는다
    plan = ps.plan_turn(base, 9, None, "취업 준비 해 보자", [])
    assert plan.path == "career" and plan.appended == [NEAR_MISS_LINE]


def test_burnout_hint_is_skipped_when_senior_says_rest():
    track = ps.fold(views("c1_t1_a", "c1_t2_a", "c2_t3_c", "c2_t4_c", "c3_t5_a"))
    assert ps.appended_lines(track, 5, "c3_t6_a", ps.apply_turn(track, ps.TurnView(5, "c3_t6_a"))) == [BURNOUT_LINE]
    assert ps.appended_lines(track, 5, "c3_t6_c", ps.apply_turn(track, ps.TurnView(5, "c3_t6_c"))) == []
    assert ps.appended_lines(track, 5, None, None, "너무 무리하지 말고 쉬엄쉬엄 하자") == []
    assert ps.appended_lines(track, 5, None, None, "시험 범위부터 같이 보자") == [BURNOUT_LINE]


def test_section_choice_notes_give_way_to_user_interests():
    notes: list = []
    for turn, choice_id in enumerate(["c1_t1_a", "c1_t2_a", "c2_t3_a", "c2_t4_a", "c3_t5_a", "c3_t6_a", "c4_t7_a", "c4_t8_a", "c5_t9_a"]):
        notes = ps.updated_notes(notes, CHOICES[choice_id].label, choice_id, turn)
    assert all(n.importance == "low" for n in notes)
    notes = ps.updated_notes(notes, "나는 그림 그리는 걸 좋아해", None, 9)
    assert any(n.field == "interest" for n in notes) and len(notes) <= 10


def test_copying_scene_example_is_corrected():
    project = puruma_project()
    codes = [v.code for v in validate_lines(project, 0, [("푸르마", CHOICES["c1_t1_a"].reply)], [], "선배")]
    assert codes == ["copied_example"]
    assert validate_lines(project, 0, [("푸르마", "우와, 지도 보니까 길이 한눈에 보여요! 선배 덕분이에요.")], [], "선배") == []
    fridge = get_project("fridge", "scenario_draft_v1")
    assert "copied_example" not in [v.code for v in validate_lines(fridge, 0, [("냉장고 회장", fridge.scenes[0].choices[0].reference_reply)], [], "민트")]
