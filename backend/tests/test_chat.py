"""채팅 / RAG / User Note / 스트리밍 테스트."""

from __future__ import annotations

import json


async def test_chat_returns_response_and_state(client, demo_session):
    response = await client.post(
        "/api/chat",
        headers=demo_session["headers"],
        json={
            "conversation_id": demo_session["conversation_id"],
            "message": "오늘 하루는 어땠어?",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"].strip()
    assert body["provider"] == "mock"
    assert body["state"]["turn_count"] == 1
    assert body["state"]["affinity"] > 10
    assert isinstance(body["sources"], list)

    # 첫 턴 스토리 이벤트(달의 문) 발생
    assert body["story_events"]
    assert body["state"]["chapter"] >= 2

    messages = await client.get(
        f"/api/conversations/{demo_session['conversation_id']}/messages",
        headers=demo_session["headers"],
    )
    assert len(messages.json()) == 3


async def test_user_note_is_saved_and_used_in_next_turn(client, demo_session):
    first = await client.post(
        "/api/chat",
        headers=demo_session["headers"],
        json={
            "conversation_id": demo_session["conversation_id"],
            "message": "내 이름은 지우야. 나는 마카롱을 좋아해.",
        },
    )
    assert first.status_code == 200
    saved = first.json()["notes_updated"]
    keys = {note["key"] for note in saved}
    assert "이름" in keys
    assert any(key.startswith("선호_") for key in keys)

    notes = await client.get("/api/notes", headers=demo_session["headers"])
    assert notes.status_code == 200
    values = {note["key"]: note["value"] for note in notes.json()}
    assert values["이름"] == "지우"

    second = await client.post(
        "/api/chat",
        headers=demo_session["headers"],
        json={
            "conversation_id": demo_session["conversation_id"],
            "message": "내 이름 기억해?",
        },
    )
    assert second.status_code == 200
    assert "지우" in second.json()["reply"]


async def test_manual_note_management(client, demo_session):
    created = await client.post(
        "/api/notes",
        headers=demo_session["headers"],
        json={"key": "좋아하는 계절", "value": "겨울", "category": "preference"},
    )
    assert created.status_code == 201
    note_id = created.json()["id"]

    updated = await client.patch(
        f"/api/notes/{note_id}",
        headers=demo_session["headers"],
        json={"value": "초겨울", "importance": 0.9},
    )
    assert updated.status_code == 200
    assert updated.json()["value"] == "초겨울"

    deleted = await client.delete(
        f"/api/notes/{note_id}", headers=demo_session["headers"]
    )
    assert deleted.status_code == 204


async def test_chat_rejects_empty_message(client, demo_session):
    response = await client.post(
        "/api/chat",
        headers=demo_session["headers"],
        json={"conversation_id": demo_session["conversation_id"], "message": ""},
    )
    assert response.status_code == 422


async def test_streaming_chat(client, demo_session):
    async with client.stream(
        "POST",
        "/api/chat/stream",
        headers=demo_session["headers"],
        json={
            "conversation_id": demo_session["conversation_id"],
            "message": "달의 마탑 이야기를 들려줘.",
        },
    ) as response:
        assert response.status_code == 200
        text = "".join([chunk async for chunk in response.aiter_text()])

    assert "event: token" in text
    assert "event: final" in text

    data_lines = [line for line in text.splitlines() if line.startswith("data: ")]
    final = json.loads(data_lines[-1][len("data: ") :])
    assert final["reply"]
    assert final["state"]["turn_count"] == 1
