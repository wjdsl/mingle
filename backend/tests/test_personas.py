"""기본 엔드포인트 / 페르소나 테스트."""

from __future__ import annotations


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"
    assert body["llm"]["provider"] == "mock"
    assert body["personas"] >= 3


async def test_persona_list(client):
    response = await client.get("/api/personas")
    assert response.status_code == 200
    personas = response.json()
    slugs = {persona["slug"] for persona in personas}
    assert {"seo-harin", "kai-orbital7", "momo-dalkom"} <= slugs


async def test_persona_detail(client):
    response = await client.get("/api/personas/seo-harin")
    assert response.status_code == 200
    persona = response.json()
    assert persona["name"] == "서하린"
    assert persona["knowledge_count"] >= 5
    assert persona["starter_questions"]


async def test_persona_not_found(client):
    response = await client.get("/api/personas/does-not-exist")
    assert response.status_code == 404
