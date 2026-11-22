"""작품별 채팅·공유 통계와 작품 담당자 권한 테스트."""

from __future__ import annotations

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Conversation, Persona
from app.services.story_scene_sets import scenario_persona_slug
from app.services.story_scenes import PROJECTS
from scripts.create_admin import provision

ADMIN = {"email": "admin@test.local", "password": "testpass12345"}
PASSWORD = "project-pass-12345"
PROJECTS_ALL = ("puruma", "fridge", "cloud")


async def _headers(client, email=ADMIN["email"], password=ADMIN["password"]):
    response = await client.post("/api/admin/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _stats(client, headers, project, days=14):
    response = await client.get(f"/api/admin/projects/{project}/stats", params={"days": days}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _story_session(client, project, scene_set=None):
    session = await client.post("/api/sessions", json={"display_name": "통계제외호칭"})
    headers = {"X-Personal-Code": session.json()["personal_code"]}
    body = {"project": project, **({"scene_set": scene_set} if scene_set else {})}
    created = await client.post("/api/story-chat/conversations", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return headers, created.json()["conversation_id"]


def _turn(turn, request_id, text="함께 가 볼게요."):
    return {"request_id": request_id, "turn": turn, "input": {"text": text}}


async def _event(client, anon, project, event):
    return await client.post("/api/events/share", json={"anon_id": anon, "project": project, "event": event})


async def test_chat_stats_are_counted_per_project_and_retries_are_not_double_counted(client):
    admin = await _headers(client)
    before = {p: await _stats(client, admin, p) for p in PROJECTS_ALL}

    # 푸르마 1턴
    puruma = await client.post("/api/sessions", json={"persona_slug": "puruma"})
    code = puruma.json()["personal_code"]
    response = await client.post(
        "/api/chat",
        headers={"X-Personal-Code": code},
        json={"conversation_id": puruma.json()["conversation"]["id"], "message": "같이 학교를 둘러볼까요?"},
    )
    assert response.status_code == 200, response.text

    # 냉장고: 이전 장면 세트 2턴 + 재시도, 현재 시나리오 세트 1턴
    headers, cid = await _story_session(client, "fridge", "ui_mock_v1")
    url = f"/api/story-chat/conversations/{cid}/turns"
    for turn in range(2):
        assert (await client.post(url, json=_turn(turn, f"fridge-old-{turn:02d}-abcdef"), headers=headers)).status_code == 200
    retry = await client.post(url, json=_turn(1, "fridge-old-01-abcdef"), headers=headers)
    assert retry.status_code == 200 and retry.json()["replayed"] is True
    headers2, cid2 = await _story_session(client, "fridge", "scenario_draft_v1")
    ok = await client.post(f"/api/story-chat/conversations/{cid2}/turns", json=_turn(0, "fridge-new-00-abcdef"), headers=headers2)
    assert ok.status_code == 200, ok.text

    # 위기 안내로 저장되지 않은 입력은 진행 턴에 포함하지 않는다.
    crisis = await client.post(f"/api/story-chat/conversations/{cid2}/turns", json=_turn(1, "fridge-crisis-0001", "죽고 싶어요"), headers=headers2)
    assert crisis.json()["safety_notice"] is True

    after = {p: await _stats(client, admin, p) for p in PROJECTS_ALL}

    def delta(project, section, key):
        return after[project][section][key] - before[project][section][key]

    assert delta("puruma", "chat", "conversations") == 1 and delta("puruma", "chat", "turns") == 1
    assert delta("fridge", "chat", "conversations") == 2 and delta("fridge", "chat", "sessions") == 2
    assert delta("fridge", "chat", "turns") == 3  # 2 + 1, 재시도·위기 안내 제외
    assert delta("cloud", "chat", "conversations") == 0 and delta("cloud", "chat", "turns") == 0
    assert sum(d["conversations"] for d in after["fridge"]["daily"]) == after["fridge"]["chat"]["conversations"]
    assert sum(d["turns"] for d in after["fridge"]["daily"]) == after["fridge"]["chat"]["turns"]
    assert after["fridge"]["chat"]["completed_conversations"] == 0
    assert "통계제외호칭" not in str(after) and "함께 가 볼게요" not in str(after)


async def test_completion_rate_counts_completed_story_conversations(client):
    admin = await _headers(client)
    before = await _stats(client, admin, "cloud")
    headers, cid = await _story_session(client, "cloud", "scenario_draft_v1")
    url = f"/api/story-chat/conversations/{cid}/turns"
    for turn in range(9):
        assert (await client.post(url, json=_turn(turn, f"cloud-{turn:02d}-abcdef"), headers=headers)).status_code == 200
    fixed = await client.post(
        f"/api/story-chat/conversations/{cid}/fixed-turns", json={"request_id": "cloud-ending-abcdef", "turn": 9}, headers=headers
    )
    assert fixed.status_code == 200 and fixed.json()["finished"]
    after = await _stats(client, admin, "cloud")
    assert after["chat"]["completed_conversations"] - before["chat"]["completed_conversations"] == 1
    assert after["chat"]["turns"] - before["chat"]["turns"] == 10
    assert after["chat"]["completion_rate"] is not None


async def test_stats_include_conversations_from_both_scene_set_personas(client):
    await _story_session(client, "cloud", "ui_mock_v1")
    await _story_session(client, "cloud", "scenario_draft_v1")
    async with SessionLocal() as db:
        slugs = {PROJECTS["cloud"].persona_slug, scenario_persona_slug(PROJECTS["cloud"].persona_slug)}
        found = (await db.execute(
            select(Persona.slug).join(Conversation, Conversation.persona_id == Persona.id).where(Persona.slug.in_(slugs))
        )).scalars().all()
    assert set(found) == slugs
    assert (await _stats(client, await _headers(client), "cloud"))["chat"]["conversations"] >= 2


async def test_project_admin_is_limited_to_assigned_projects(client):
    await provision("owner@fridge", "담당자", PASSWORD, False, ["fridge"])
    owner = await _headers(client, "owner@fridge", PASSWORD)
    assert (await client.get("/api/admin/projects", headers=owner)).json() == ["fridge"]
    assert (await client.get("/api/admin/projects/fridge/stats", headers=owner)).status_code == 200
    for other in ("puruma", "cloud"):
        denied = await client.get(f"/api/admin/projects/{other}/stats", headers=owner)
        assert denied.status_code == 403
    assert (await client.get("/api/admin/projects/unknown/stats", headers=owner)).status_code == 422
    assert (await client.get("/api/admin/projects/fridge/stats")).status_code == 401
    for path in ("/overview", "/conversations", "/triggers"):
        assert (await client.get(f"/api/admin{path}", headers=owner)).status_code == 403
    platform = await _headers(client)
    assert (await client.get("/api/admin/projects", headers=platform)).json() == list(PROJECTS_ALL)
    # 작품이 없는 담당자는 아무 작품도 볼 수 없다.
    await provision("none@x", "담당자", PASSWORD, False, ["puruma"])
    async with SessionLocal() as db:
        from app.db.models import AdminProjectAccess
        from sqlalchemy import delete
        await db.execute(delete(AdminProjectAccess))
        await db.commit()
    nobody = await _headers(client, "none@x", PASSWORD)
    assert (await client.get("/api/admin/projects/puruma/stats", headers=nobody)).status_code == 403


async def test_share_events_update_only_their_own_metrics(client):
    admin = await _headers(client)
    before = await _stats(client, admin, "cloud")
    other_before = await _stats(client, admin, "fridge")

    assert (await _event(client, "anon-aaaa-0001", "cloud", "share_click")).status_code == 204
    assert (await _event(client, "anon-aaaa-0001", "cloud", "share_click")).status_code == 204
    s = (await _stats(client, admin, "cloud"))["share"]
    assert (s["share_clicks"], s["image_save_clicks"], s["link_opens"], s["link_start_sessions"]) == tuple(
        before["share"][k] + d for k, d in (("share_clicks", 2), ("image_save_clicks", 0), ("link_opens", 0), ("link_start_sessions", 0)))

    await _event(client, "anon-aaaa-0001", "cloud", "image_save_click")
    await _event(client, "anon-bbbb-0002", "cloud", "link_open")
    await _event(client, "anon-bbbb-0002", "cloud", "link_open")  # 같은 세션의 재열기는 한 번
    await _event(client, "anon-bbbb-0002", "cloud", "link_start")
    await _event(client, "anon-bbbb-0002", "cloud", "link_start")
    await _event(client, "anon-cccc-0003", "cloud", "link_open")  # 열기만 하고 시작하지 않음
    after = (await _stats(client, admin, "cloud"))["share"]
    assert after["share_clicks"] - before["share"]["share_clicks"] == 2
    assert after["image_save_clicks"] - before["share"]["image_save_clicks"] == 1
    assert after["link_opens"] - before["share"]["link_opens"] == 2
    assert after["link_start_sessions"] - before["share"]["link_start_sessions"] == 1
    assert (await _stats(client, admin, "fridge"))["share"] == other_before["share"]
    # 공유 이벤트는 대화 지표에 영향을 주지 않는다.
    assert (await _stats(client, admin, "cloud"))["chat"] == before["chat"]


async def test_share_event_input_is_restricted(client):
    for body in (
        {"anon_id": "short", "project": "cloud", "event": "share_click"},
        {"anon_id": "anon-aaaa-0001", "project": "momo", "event": "share_click"},
        {"anon_id": "anon-aaaa-0001", "project": "cloud", "event": "page_view"},
        {"anon_id": "anon-aaaa-0001", "project": "cloud", "event": "share_click", "nickname": "민트"},
    ):
        assert (await client.post("/api/events/share", json=body)).status_code == 422


async def test_puruma_safety_notice_is_not_counted_as_a_turn(client):
    admin = await _headers(client)
    before = await _stats(client, admin, "puruma")
    session = await client.post("/api/sessions", json={"persona_slug": "puruma"})
    code, cid = session.json()["personal_code"], session.json()["conversation"]["id"]
    safe = await client.post("/api/chat", headers={"X-Personal-Code": code}, json={"conversation_id": cid, "message": "죽고 싶어요"})
    assert safe.status_code == 200 and safe.json()["safety_notice"] is True
    after = await _stats(client, admin, "puruma")
    assert after["chat"]["conversations"] - before["chat"]["conversations"] == 1
    assert after["chat"]["turns"] == before["chat"]["turns"]
    assert after["chat"]["messages"] - before["chat"]["messages"] <= 1  # 새 대화의 인사 메시지만, 위기 입력은 저장 안 됨


async def test_stats_period_excludes_older_conversations(client):
    admin = await _headers(client)
    _, cid = await _story_session(client, "cloud", "scenario_draft_v1")
    wide_before = await _stats(client, admin, "cloud", days=30)
    narrow_before = await _stats(client, admin, "cloud", days=7)
    from datetime import timedelta
    from app.db.models import utcnow
    async with SessionLocal() as db:
        conversation = await db.get(Conversation, cid)
        conversation.created_at = utcnow() - timedelta(days=20)
        await db.commit()
    assert (await _stats(client, admin, "cloud", days=7))["chat"]["conversations"] == narrow_before["chat"]["conversations"] - 1
    assert (await _stats(client, admin, "cloud", days=30))["chat"]["conversations"] == wide_before["chat"]["conversations"]
    assert (await client.get("/api/admin/projects/cloud/stats", params={"days": 0}, headers=admin)).status_code == 422
