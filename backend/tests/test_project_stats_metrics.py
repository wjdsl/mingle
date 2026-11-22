"""대시보드 1차 지표: 샘플 구분, 구간 도달률, 엔딩 분포, 체류 시간, 관심 분야, AI 대체 응답 비율.

테스트 서버는 Mock LLM이라 API로 만든 대화는 모두 샘플(provider=mock)이다. 실제 대화는 저장된 턴의
provider를 DB에서 gemini·fallback으로 바꿔 흉내 낸다. 다른 테스트의 대화는 조회 기간 밖으로 옮겨 격리한다.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from app.db.base import SessionLocal
from app.db.models import Conversation, Message, Persona, StoryTurnRecord, utcnow
from app.services.project_stats import _median, _percentile, project_persona_slugs
from app.services.story_data import load_draft
from scripts.create_admin import provision

ADMIN = {"email": "admin@test.local", "password": "testpass12345"}
PASSWORD = "project-pass-12345"
PRIVATE_NICKNAME = "통계비공개호칭"
PRIVATE_TEXT = "비공개 자유 입력 문장"


async def _headers(client, email=ADMIN["email"], password=ADMIN["password"]):
    response = await client.post("/api/admin/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _stats(client, headers, project, data="real", days=14):
    response = await client.get(f"/api/admin/projects/{project}/stats", params={"days": days, "data": data}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _isolate(project):
    """이전 테스트가 만든 이 작품의 대화를 조회 기간(최대 90일) 밖으로 옮긴다."""
    async with SessionLocal() as db:
        persona_ids = select(Persona.id).where(Persona.slug.in_(project_persona_slugs(project)))
        await db.execute(
            update(Conversation).where(Conversation.persona_id.in_(persona_ids)).values(created_at=utcnow() - timedelta(days=200))
        )
        await db.commit()


async def _conversation(client, project, scene_set):
    session = await client.post("/api/sessions", json={"display_name": PRIVATE_NICKNAME})
    headers = {"X-Personal-Code": session.json()["personal_code"]}
    created = await client.post("/api/story-chat/conversations", json={"project": project, "scene_set": scene_set}, headers=headers)
    assert created.status_code == 201, created.text
    return headers, created.json()["conversation_id"]


async def _play(client, headers, cid, turns, choices=None, prefix="t"):
    """turns개 장면을 진행한다. choices[i]가 있으면 버튼, 없으면 자유 입력. 마지막 응답을 돌려준다."""
    last = None
    for turn in range(turns):
        choice = (choices or {}).get(turn)
        body = {"request_id": f"{prefix}-{cid[:8]}-{turn:02d}", "turn": turn,
                "input": {"text": LABELS[choice] if choice else PRIVATE_TEXT, **({"choice_id": choice} if choice else {})}}
        response = await client.post(f"/api/story-chat/conversations/{cid}/turns", json=body, headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
    return last


async def _fixed_last(client, headers, cid):
    response = await client.post(
        f"/api/story-chat/conversations/{cid}/fixed-turns", json={"request_id": f"fx-{cid[:8]}-09", "turn": 9}, headers=headers
    )
    assert response.status_code == 200 and response.json()["finished"], response.text
    return response.json()


async def _set_providers(cid, providers: dict[int, str], reason: str | None = None, seconds_apart: int | None = None):
    """저장된 턴의 provider를 바꾼다. fallback이면 사유 코드를 응답 메시지 extra에 넣는다."""
    async with SessionLocal() as db:
        records = (await db.execute(
            select(StoryTurnRecord).where(StoryTurnRecord.conversation_id == cid).order_by(StoryTurnRecord.turn_index)
        )).scalars().all()
        base = utcnow() - timedelta(hours=1)
        for record in records:
            if record.turn_index in providers:
                record.provider = providers[record.turn_index]
                if providers[record.turn_index] == "fallback":
                    message = await db.get(Message, record.assistant_message_id)
                    message.extra = {**(message.extra or {}), "story_fallback": {"reason": reason or "provider_http_503"}}
            if seconds_apart is not None:
                record.created_at = base + timedelta(seconds=record.turn_index * seconds_apart)
        await db.commit()


def _real(cid_turns: int) -> dict[int, str]:
    return {t: "gemini" for t in range(cid_turns)}


LABELS = {c["choice_id"]: c["label"] for s in load_draft("fridge")["turn_slots"] for c in (s["fixed_choices"] or [])}
FRIDGE_BEST = {t: f"fridge_t{t + 1:02d}_i01_btn" for t in range(9)}  # 9턴 모두 +2 → 18점 → 3단계


async def test_sample_and_real_conversations_are_separated_by_conversation(client):
    admin = await _headers(client)
    await _isolate("fridge")
    h, sample_only = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, sample_only, 3)
    h, real = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, real, 2)
    await _set_providers(real, _real(2))
    h, real_with_fallback = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, real_with_fallback, 2)
    await _set_providers(real_with_fallback, {0: "fallback", 1: "gemini"})
    h, mixed = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, mixed, 2)
    await _set_providers(mixed, {0: "gemini"})  # 1턴은 mock 그대로 → 샘플
    await _conversation(client, "fridge", "scenario_draft_v1")  # 턴 없음 → 판정 불가

    real_view = await _stats(client, admin, "fridge", "real")
    sample_view = await _stats(client, admin, "fridge", "sample")
    all_view = await _stats(client, admin, "fridge", "all")
    for view, mode in ((real_view, "real"), (sample_view, "sample"), (all_view, "all")):
        assert view["scope"] == {"mode": mode, "real_conversations": 2, "sample_conversations": 2, "unclassified_conversations": 1}
    assert real_view["chat"]["conversations"] == 3 and real_view["chat"]["turns"] == 4  # 실제 2 + 판정 불가 1
    assert sample_view["chat"]["conversations"] == 2 and sample_view["chat"]["turns"] == 5
    assert all_view["chat"]["conversations"] == 5 and all_view["chat"]["turns"] == 9
    assert sum(d["conversations"] for d in real_view["daily"]) == 3
    # 고정 연출·대체 응답은 Mock이 아니고, 대체 응답 비율은 실제 화면에만 잡힌다.
    assert real_view["fallback"]["llm_turns"] == 4 and real_view["fallback"]["fallback_turns"] == 1
    assert sample_view["fallback"]["fallback_turns"] == 0
    assert (await client.get("/api/admin/projects/fridge/stats", params={"data": "demo"}, headers=admin)).status_code == 422


async def test_segment_reach_endings_dwell_and_fallback_for_fridge(client):
    admin = await _headers(client)
    await _isolate("fridge")
    # 완주 A: 버튼으로 3단계, 완주 B: 자유 입력(Mock 분류 없음 → 0점) 1단계, 이탈 C: 5턴, 이탈 D: 0턴
    h, a = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, a, 9, FRIDGE_BEST)
    ending_a = (await _fixed_last(client, h, a))["ending"]
    h, b = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, b, 9)
    ending_b = (await _fixed_last(client, h, b))["ending"]
    h, c = await _conversation(client, "fridge", "scenario_draft_v1")
    await _play(client, h, c, 5)
    _, d = await _conversation(client, "fridge", "scenario_draft_v1")
    _, legacy = await _conversation(client, "fridge", "ui_mock_v1")  # 이전 장면 세트: 구간·엔딩 분모에서 제외
    assert (ending_a, ending_b) == ("fridge_rel_stage_3", "fridge_rel_stage_1")

    # A·B·C를 실제 대화로: 1~9턴 gemini(B의 2턴은 fallback), 10턴은 fixed 유지. 턴 간격으로 체류 시간을 정한다.
    await _set_providers(a, _real(9), seconds_apart=60)  # 9분
    await _set_providers(b, {**_real(9), 1: "fallback"}, reason="provider_timeout", seconds_apart=30)  # 4분 30초
    await _set_providers(c, {**_real(5), 3: "fallback"}, reason="provider_timeout", seconds_apart=20)  # 1분 20초

    stats = await _stats(client, admin, "fridge", "real")
    seg = stats["segments"]
    assert seg["scene_set"] == "scenario_draft_v1"
    assert seg["conversations"] == 4 and seg["legacy_conversations"] == 1  # A B C D / legacy
    assert [(s["title"], s["start_turn"], s["reached"]) for s in seg["segments"]] == [
        ("도입", 1, 4), ("전개", 4, 3), ("위기", 7, 2), ("예고편 컷", 10, 2)
    ]
    assert seg["segments"][1]["rate"] == 75.0

    endings = {e["id"]: e for e in stats["endings"]["endings"]}
    assert stats["endings"]["judged"] == 2 and stats["endings"]["unjudged_completed"] == 0
    assert list(endings) == ["fridge_rel_stage_1", "fridge_rel_stage_2", "fridge_rel_stage_3"]
    assert (endings["fridge_rel_stage_1"]["count"], endings["fridge_rel_stage_2"]["count"], endings["fridge_rel_stage_3"]["count"]) == (1, 0, 1)
    assert endings["fridge_rel_stage_3"]["rate"] == 50.0

    assert stats["dwell"] == {"conversations": 3, "median_seconds": 270, "p90_seconds": 540}

    fb = stats["fallback"]
    assert fb["llm_turns"] == 9 + 9 + 5  # 10턴 고정 연출 제외
    assert fb["fallback_turns"] == 2 and fb["rate"] == round(2 / 23 * 100, 1)
    assert fb["reasons"] == [{"code": "provider_timeout", "count": 2}]
    assert stats["interest"]["applicable"] is False and stats["interest"]["topics"] == []

    assert PRIVATE_NICKNAME not in str(stats) and PRIVATE_TEXT not in str(stats)
    assert d and legacy


async def test_cloud_segments_follow_scene_card_phases(client):
    admin = await _headers(client)
    await _isolate("cloud")
    h, cid = await _conversation(client, "cloud", "scenario_draft_v1")
    await _play(client, h, cid, 9)
    ending = (await _fixed_last(client, h, cid))["ending"]
    stats = await _stats(client, admin, "cloud", "sample")
    assert [s["title"] for s in stats["segments"]["segments"]] == ["합류", "출동", "위기", "구조", "예고편 컷"]
    assert all(s["rate"] == 100.0 for s in stats["segments"]["segments"])
    counts = {e["id"]: e["count"] for e in stats["endings"]["endings"]}
    assert len(counts) == 5 and counts[ending] == 1 and sum(counts.values()) == 1
    # 실제 화면에는 샘플 대화가 보이지 않는다.
    real = await _stats(client, admin, "cloud", "real")
    assert real["chat"]["conversations"] == 0 and real["endings"]["judged"] == 0
    assert real["scope"]["sample_conversations"] == 1


async def test_puruma_endings_and_interest_topics(client):
    admin = await _headers(client)
    await _isolate("puruma")
    h, done = await _conversation(client, "puruma", "puruma_draft_v1")
    last = await _play(client, h, done, 10)
    assert last["finished"] is True
    h, partial = await _conversation(client, "puruma", "puruma_draft_v1")
    await _play(client, h, partial, 3)
    # 자유 입력 주제를 저장된 값처럼 넣는다(Mock은 분류하지 않음). done의 0·1턴 탐구, 2턴 글로벌, 나머지는 분류 없음.
    async with SessionLocal() as db:
        records = (await db.execute(select(StoryTurnRecord).where(StoryTurnRecord.conversation_id == done))).scalars().all()
        for record in records:
            message = await db.get(Message, record.assistant_message_id)
            topic = {0: "topic_study", 1: "topic_study", 2: "topic_global"}.get(record.turn_index)
            message.extra = {**message.extra, "puruma": {**message.extra.get("puruma", {}), "topic": topic}}
        await db.commit()
    stats = await _stats(client, admin, "puruma", "sample")
    assert [s["title"] for s in stats["segments"]["segments"]] == ["개강", "적응", "중간고사", "축제", "기말·종강", "방학 계획"]
    assert [s["reached"] for s in stats["segments"]["segments"]] == [2, 2, 1, 1, 1, 1]
    ending_ids = [e["id"] for e in stats["endings"]["endings"]]
    assert len(ending_ids) == 6 and stats["endings"]["judged"] == 1
    interest = stats["interest"]
    topics = {t["id"]: t["count"] for t in interest["topics"]}
    assert interest["applicable"] is True and interest["free_inputs"] == 13
    assert topics["topic_study"] == 2 and topics["topic_global"] == 1 and interest["unclassified"] == 10
    assert [t["label"] for t in interest["topics"]] == ["탐구", "기술", "예술", "소통", "글로벌", "일상"]
    assert PRIVATE_TEXT not in str(stats)


async def test_new_metrics_follow_project_admin_permissions(client):
    await provision("owner-metrics@cloud", "담당자", PASSWORD, False, ["cloud"])
    owner = await _headers(client, "owner-metrics@cloud", PASSWORD)
    for mode in ("real", "sample", "all"):
        assert (await client.get("/api/admin/projects/cloud/stats", params={"data": mode}, headers=owner)).status_code == 200
        for other in ("puruma", "fridge"):
            assert (await client.get(f"/api/admin/projects/{other}/stats", params={"data": mode}, headers=owner)).status_code == 403


def test_percentiles():
    assert _median([]) is None and _percentile([], 0.9) is None
    assert _median([10, 20, 30]) == 20 and _median([10, 20]) == 15
    assert _percentile(list(range(1, 11)), 0.9) == 9 and _percentile([5], 0.9) == 5
