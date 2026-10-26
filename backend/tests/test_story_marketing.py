"""스토리 분기 / 마케팅 Trigger / CTA / 엔딩 테스트."""

from __future__ import annotations


async def _create_session(client, persona_slug: str):
    response = await client.post(
        "/api/sessions", json={"persona_slug": persona_slug}
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return {
        "headers": {"X-Personal-Code": data["personal_code"]},
        "conversation_id": data["conversation"]["id"],
    }


async def _chat(client, session, message: str):
    response = await client.post(
        "/api/chat",
        headers=session["headers"],
        json={"conversation_id": session["conversation_id"], "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_marketing_trigger_and_click(client):
    session = await _create_session(client, "momo-dalkom")

    first = await _chat(client, session, "오늘의 추천 메뉴는 뭐예요?")
    assert first["story_events"]
    assert first["triggers"] == []  # 아직 2턴 미만

    second = await _chat(client, session, "케이크 주문하고 싶어요")
    assert second["triggers"], "2턴 이후 트리거가 발생해야 합니다."
    cta = second["triggers"][0]["cta"]
    assert cta is not None
    assert cta["cta_type"] in {"coupon", "purchase", "booking", "event", "link"}

    click = await client.post(
        "/api/marketing/events",
        headers=session["headers"],
        json={"conversation_id": session["conversation_id"], "cta_id": cta["id"]},
    )
    assert click.status_code == 201
    assert click.json()["event_type"] == "click"

    third = await _chat(client, session, "케이크 주문할게요")
    assert third["triggers"]
    assert third["triggers"][0]["cta"]["cta_type"] == "purchase"

    events = await client.get(
        f"/api/conversations/{session['conversation_id']}/marketing-events",
        headers=session["headers"],
    )
    assert events.status_code == 200
    types = [event["event_type"] for event in events.json()]
    assert types.count("impression") >= 2
    assert "click" in types


async def test_story_timeline_and_multi_ending(client):
    session = await _create_session(client, "seo-harin")

    last = None
    for _ in range(13):
        last = await _chat(client, session, "오늘 너무 행복했어. 고마워!")

    assert last is not None
    timeline = await client.get(
        f"/api/conversations/{session['conversation_id']}/timeline",
        headers=session["headers"],
    )
    assert timeline.status_code == 200
    kinds = {entry["kind"] for entry in timeline.json()}
    assert "story" in kinds
    assert "ending" in kinds

    assert last["ending"] is not None
    assert last["ending"]["code"] in {"eternal_moonlight", "starlit_promise", "dawn_farewell"}

    detail = await client.get(
        f"/api/conversations/{session['conversation_id']}", headers=session["headers"]
    )
    assert detail.json()["status"] == "completed"
    assert detail.json()["ending_title"]

    # 엔딩 이후에는 새 메시지를 받지 않는다.
    blocked = await client.post(
        "/api/chat",
        headers=session["headers"],
        json={"conversation_id": session["conversation_id"], "message": "계속 이야기하자"},
    )
    assert blocked.status_code == 409


async def test_share_card(client):
    session = await _create_session(client, "kai-orbital7")
    await _chat(client, session, "오비탈 7은 어떤 곳이야?")

    created = await client.post(
        f"/api/conversations/{session['conversation_id']}/share",
        headers=session["headers"],
        json={"include_messages": 4},
    )
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["slug"]
    assert card["payload"]["persona"]["name"] == "카이"
    assert card["payload"]["messages"]

    public = await client.get(f"/api/share/{card['slug']}")
    assert public.status_code == 200
    assert public.json()["views"] >= 1


async def test_share_not_found(client):
    response = await client.get("/api/share/unknown-slug")
    assert response.status_code == 404
