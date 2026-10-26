"""관리자 로그인 / B2B Dashboard 테스트."""

from __future__ import annotations

ADMIN_EMAIL = "admin@test.local"
ADMIN_PASSWORD = "testpass123"


async def _login(client):
    response = await client.post(
        "/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_login_failure(client):
    response = await client.post(
        "/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 401


async def test_dashboard_requires_auth(client):
    response = await client.get("/api/admin/overview")
    assert response.status_code == 401


async def test_dashboard_overview(client):
    # 대시보드에 집계될 데이터 생성
    created = await client.post(
        "/api/sessions", json={"persona_slug": "momo-dalkom"}
    )
    code = created.json()["personal_code"]
    conversation_id = created.json()["conversation"]["id"]
    await client.post(
        "/api/chat",
        headers={"X-Personal-Code": code},
        json={"conversation_id": conversation_id, "message": "케이크 주문할게요"},
    )

    headers = await _login(client)
    response = await client.get("/api/admin/overview?days=14", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["totals"]["sessions"] >= 1
    assert body["totals"]["conversations"] >= 1
    assert body["totals"]["messages"] >= 2
    assert len(body["personas"]) == 3
    assert len(body["triggers"]) >= 8
    assert len(body["daily"]) == 14
    assert "totals" in body

    triggers = await client.get("/api/admin/triggers", headers=headers)
    assert triggers.status_code == 200
    assert len(triggers.json()) >= 8

    conversations = await client.get("/api/admin/conversations", headers=headers)
    assert conversations.status_code == 200
    assert conversations.json()

    detail = await client.get(
        f"/api/admin/conversations/{conversation_id}", headers=headers
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["persona"]["slug"] == "momo-dalkom"
    assert len(payload["messages"]) >= 2


async def test_admin_me(client):
    headers = await _login(client)
    response = await client.get("/api/admin/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL
