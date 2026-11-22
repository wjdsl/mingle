"""관리자 로그인 / B2B Dashboard 테스트."""

from __future__ import annotations

ADMIN_EMAIL = "admin@test.local"
ADMIN_PASSWORD = "testpass12345"


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
    for path in ["/overview", "/me", "/conversations", "/conversations/nonexistent", "/triggers", "/triggers/nonexistent/config"]:
        response = await client.get(f"/api/admin{path}")
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
    assert len(body["personas"]) == 4  # 시드 데모 3종 + 푸르마
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


async def test_admin_token_and_role_boundaries(client):
    from datetime import timedelta
    import jwt
    from app.core.config import settings
    from app.core.security import create_access_token, hash_password
    from app.db.base import SessionLocal
    from app.db.models import AdminUser, utcnow

    async with SessionLocal() as db:
        viewer = AdminUser(email="viewer@test.local", password_hash=hash_password("test-only-password"), role="viewer")
        inactive = AdminUser(email="inactive@test.local", password_hash=hash_password("test-only-password"), is_active=False)
        db.add_all([viewer, inactive]); await db.commit()
        denied_tokens = [create_access_token(viewer.id), create_access_token(inactive.id)]
    expired = jwt.encode({"sub": "expired", "exp": utcnow() - timedelta(minutes=1)}, settings.secret_key, algorithm="HS256")
    for token in ["invalid-token", expired, *denied_tokens]:
        response = await client.get("/api/admin/overview", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code in (401, 403)
    denied_login = await client.post("/api/admin/login", json={"email": "viewer@test.local", "password": "test-only-password"})
    assert denied_login.status_code == 403
    headers = await _login(client)
    assert (await client.get('/api/admin/me', headers=headers)).headers['cache-control'] == 'no-store'
    for days in [0, 91]:
        assert (await client.get(f"/api/admin/overview?days={days}", headers=headers)).status_code == 422


async def test_overview_calendar_range_is_consistent(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.db.base import SessionLocal
    from app.db.models import Conversation, Message, Persona, RelationshipState, UserSession
    import app.services.analytics as analytics

    # 11/11 00:30 KST: rolling 24 hours would incorrectly include yesterday.
    now = datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(analytics, "utcnow", lambda: now)
    async with SessionLocal() as db:
        persona = (await db.execute(select(Persona))).scalars().first()
        ids = []
        for age, stage in [(timedelta(days=2), "기간외"), (timedelta(hours=1), "어제"), (timedelta(minutes=10), "오늘")]:
            created = now - age
            session = UserSession(code_hash=f"range-{stage}", created_at=created)
            db.add(session); await db.flush()
            conversation = Conversation(session_id=session.id, persona_id=persona.id, created_at=created, last_message_at=created, status="completed")
            db.add(conversation); await db.flush()
            db.add(RelationshipState(conversation_id=conversation.id, stage=stage))
            db.add(Message(conversation_id=conversation.id, role="assistant", content="test", created_at=created, latency_ms=100))
            ids.append(conversation.id)
        # A message today in an older conversation counts as today's activity,
        # while that conversation must stay outside today's start cohort.
        db.add(Message(conversation_id=ids[0], role="assistant", content="resumed", created_at=now, latency_ms=200))
        await db.commit()
        short = await analytics.build_overview(db, 1)
        long = await analytics.build_overview(db, 3)
    assert short.totals.sessions == 1
    assert short.totals.conversations == short.totals.completed_conversations == 1
    assert short.totals.messages == 2
    assert sum(p.messages for p in short.personas) == short.totals.messages
    assert short.daily[0].date == "2026-11-11"
    assert sum(p.conversations for p in short.daily) == short.totals.conversations
    assert sum(p.messages for p in short.daily) == short.totals.messages
    assert sum(p.conversations for p in short.personas) == 1
    assert short.stages == {"오늘": 1}
    assert {c.conversation_id for c in short.recent_conversations} == {ids[-1]}
    assert long.totals.conversations == 3


async def test_admin_requires_private_signing_key(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production-please-use-32-bytes")
    response = await client.post("/api/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 503


async def test_legacy_default_password_is_not_a_usable_admin(client):
    from app.core.security import create_access_token, hash_password
    from app.db.base import SessionLocal
    from app.db.models import AdminUser
    async with SessionLocal() as db:
        legacy = AdminUser(email="legacy@test.local", password_hash=hash_password("admin1234!"), role="admin")
        db.add(legacy); await db.commit()
        token = create_access_token(legacy.id)
    login = await client.post("/api/admin/login", json={"email": "legacy@test.local", "password": "admin1234!"})
    assert login.status_code == 403
    overview = await client.get("/api/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert overview.status_code == 403


async def test_project_overviews_count_only_their_chat_activity(client):
    admin = await _login(client)
    path = "/api/admin/overview"
    projects = ("puruma", "fridge", "cloud")

    async def overview(project):
        response = await client.get(path, params={"project": project, "days": 14}, headers=admin)
        assert response.status_code == 200, response.text
        return response.json()

    assert (await client.get(path, params={"project": "fridge"})).status_code == 401
    assert (await client.get(path, params={"project": "momo-dalkom"}, headers=admin)).status_code == 422
    before = {project: await overview(project) for project in projects}

    puruma = await client.post("/api/sessions", json={"persona_slug": "puruma"})
    assert puruma.status_code == 201
    puruma_id = puruma.json()["conversation"]["id"]
    response = await client.post(
        "/api/chat",
        headers={"X-Personal-Code": puruma.json()["personal_code"]},
        json={"conversation_id": puruma_id, "message": "같이 학교를 둘러볼까요?"},
    )
    assert response.status_code == 200, response.text

    story_ids = {}
    for project, scene_set, input_turns in (("fridge", "ui_mock_v1", 1), ("cloud", "scenario_draft_v1", 9)):
        session = await client.post("/api/sessions", json={"display_name": "집계에포함하지않을호칭"})
        assert session.status_code == 201
        headers = {"X-Personal-Code": session.json()["personal_code"]}
        created = await client.post(
            "/api/story-chat/conversations",
            json={"project": project, "scene_set": scene_set},
            headers=headers,
        )
        assert created.status_code == 201
        story_ids[project] = created.json()["conversation_id"]
        url = f"/api/story-chat/conversations/{story_ids[project]}/turns"
        for turn in range(input_turns):
            payload = {"request_id": f"dashboard-test-{turn}", "turn": turn, "input": {"text": "함께 진행해 볼게요."}}
            response = await client.post(url, json=payload, headers=headers)
            assert response.status_code == 200, response.text
        replay = await client.post(url, json=payload, headers=headers)
        assert replay.status_code == 200 and replay.json()["replayed"]
        if project == "cloud":
            fixed = await client.post(
                f"/api/story-chat/conversations/{story_ids[project]}/fixed-turns",
                json={"request_id": "dashboard-cloud-ending", "turn": input_turns},
                headers=headers,
            )
            assert fixed.status_code == 200 and fixed.json()["finished"]

    for project, conversation_id, turns, messages, completed in (
        ("puruma", puruma_id, 1, 3, 0),  # 푸르마는 첫 인사도 저장합니다.
        ("fridge", story_ids["fridge"], 1, 2, 0),
        ("cloud", story_ids["cloud"], 10, 19, 1),  # 마지막 장면은 캐릭터 대사만 집계합니다.
    ):
        result = await overview(project)
        for metric, delta in (("sessions", 1), ("conversations", 1), ("messages", messages), ("completed_conversations", completed)):
            assert result["totals"][metric] - before[project]["totals"][metric] == delta, (project, metric)
        for metric in ("sessions", "conversations", "messages"):
            assert sum(day[metric] for day in result["daily"]) == result["totals"][metric]
        recent = {row["conversation_id"]: row for row in result["recent_conversations"]}
        assert recent[conversation_id]["turn_count"] == turns
        assert recent[conversation_id]["session_hint"] == "****"
        assert all(other_id not in recent for other_id in [puruma_id, *story_ids.values()] if other_id != conversation_id)
        assert all(persona["slug"] != "momo-dalkom" for persona in result["personas"])
        assert "집계에포함하지않을호칭" not in str(result)
        assert "함께 진행해 볼게요." not in str(result)
