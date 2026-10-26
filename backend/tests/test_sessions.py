"""비회원 세션 / 개인 코드 / 대화 목록 테스트."""

from __future__ import annotations

import re


async def test_create_session_with_personal_code(client):
    response = await client.post(
        "/api/sessions", json={"display_name": "새 사용자", "persona_slug": "momo-dalkom"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert re.fullmatch(r"COMP-[A-Z2-9]{4}-[A-Z2-9]{4}", body["personal_code"])
    assert body["conversation"]["persona_name"] == "모모"
    assert body["session"]["display_name"] == "새 사용자"

    me = await client.get(
        "/api/sessions/me",
        headers={"X-Personal-Code": body["personal_code"]},
    )
    assert me.status_code == 200
    assert me.json()["id"] == body["session"]["id"]


async def test_resume_session_restores_conversations(client):
    created = await client.post(
        "/api/sessions", json={"persona_slug": "kai-orbital7"}
    )
    assert created.status_code == 201
    code = created.json()["personal_code"]

    resumed = await client.post("/api/sessions/resume", json={"personal_code": code})
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["session"]["id"] == created.json()["session"]["id"]
    assert len(body["conversations"]) == 1
    assert body["conversations"][0]["persona_slug"] == "kai-orbital7"


async def test_resume_with_invalid_code(client):
    response = await client.post(
        "/api/sessions/resume", json={"personal_code": "COMP-XXXX-YYYY"}
    )
    assert response.status_code == 401


async def test_session_requires_code(client):
    response = await client.get("/api/sessions/me")
    assert response.status_code == 401


async def test_conversation_lifecycle(client, demo_session):
    headers = demo_session["headers"]

    listed = await client.get("/api/conversations", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    conversation_id = demo_session["conversation_id"]
    detail = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["message_count"] == 1  # 인사 메시지

    messages = await client.get(
        f"/api/conversations/{conversation_id}/messages", headers=headers
    )
    assert messages.status_code == 200
    assert messages.json()[0]["role"] == "assistant"
    assert messages.json()[0]["extra"]["kind"] == "greeting"

    state = await client.get(
        f"/api/conversations/{conversation_id}/state", headers=headers
    )
    assert state.status_code == 200
    assert state.json()["stage"] == "낯섦"
    assert state.json()["turn_count"] == 0

    renamed = await client.patch(
        f"/api/conversations/{conversation_id}",
        headers=headers,
        json={"title": "달빛 대화"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "달빛 대화"


async def test_cannot_access_other_users_conversation(client, demo_session):
    other = await client.post("/api/sessions", json={})
    other_code = other.json()["personal_code"]

    response = await client.get(
        f"/api/conversations/{demo_session['conversation_id']}",
        headers={"X-Personal-Code": other_code},
    )
    assert response.status_code == 404
