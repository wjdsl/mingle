"""대시보드 2차: 이벤트 수집(/api/events/track), 총 접속 수, 홍보 노출·클릭, 재방문율, CSV.

테스트 서버는 Mock LLM이라 기본으로 받은 이벤트는 샘플이다. 실제 이벤트는 수집 경로의 공급자 이름을 바꿔 흉내 낸다.
작품마다 이 테스트 전용 기간을 만들기 어려워, 시작 시 그 작품의 기존 이벤트를 조회 기간 밖으로 옮겨 격리한다.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.api.routes import events as events_route
from app.db.base import SessionLocal
from app.db.models import AnalyticsEvent, utcnow
from app.services.analytics_events import promo_contents
from scripts.create_admin import provision

ADMIN = {"email": "admin@test.local", "password": "testpass12345"}
PASSWORD = "project-pass-12345"
PROMO = "rag_library_central"
PROMO2 = "rag_career_center"


async def _headers(client, email=ADMIN["email"], password=ADMIN["password"]):
    response = await client.post("/api/admin/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _stats(client, headers, project, data="real"):
    response = await client.get(f"/api/admin/projects/{project}/stats", params={"data": data}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _isolate(project):
    async with SessionLocal() as db:
        await db.execute(update(AnalyticsEvent).where(AnalyticsEvent.project == project)
                         .values(created_at=utcnow() - timedelta(days=200)))
        await db.commit()


def _sid(n: int) -> str:
    return f"sess-{n:04d}-abcdef"


def _vid(n: int) -> str:
    return f"visitor-{n:04d}-abcdef"


async def _track(client, session, project, event, **extra):
    return await client.post("/api/events/track", json={"session_id": session, "project": project, "event_type": event, **extra})


@pytest.fixture
def real_server(monkeypatch):
    """수집 시점의 서버가 실제 공급자(gemini)로 동작하는 것처럼 바꾼다."""
    monkeypatch.setattr(events_route, "get_llm", lambda: SimpleNamespace(name="gemini"))


async def test_track_input_is_restricted(client):
    ok = await _track(client, _sid(1), "puruma", "promo_impression", content_id=PROMO, section="s3_midterm", turn=4)
    assert ok.status_code == 204
    bad = [
        {"session_id": "short", "project": "puruma", "event_type": "entry_view"},
        {"session_id": _sid(1), "project": "momo", "event_type": "entry_view"},
        {"session_id": _sid(1), "project": "puruma", "event_type": "page_view"},
        {"session_id": _sid(1), "project": "puruma", "event_type": "entry_view", "nickname": "민트"},
        {"session_id": _sid(1), "project": "puruma", "event_type": "entry_view", "message": "대화 원문"},
        {"session_id": _sid(1), "project": "puruma", "event_type": "promo_click", "content_id": "rag_unknown"},
        {"session_id": _sid(1), "project": "puruma", "event_type": "promo_click"},  # 콘텐츠 ID 없음
        {"session_id": _sid(1), "project": "puruma", "event_type": "entry_view", "content_id": PROMO},  # 홍보가 아닌데 콘텐츠
        {"session_id": _sid(1), "project": "puruma", "event_type": "entry_view", "visitor_id": _vid(1)},  # 시작·완료만
        {"session_id": _sid(1), "project": "fridge", "event_type": "promo_click", "content_id": PROMO},  # 다른 작품 콘텐츠
        {"session_id": _sid(1), "project": "cloud", "event_type": "promo_impression", "content_id": "cinema_link"},  # URL 미정
        {"session_id": _sid(1), "project": "puruma", "event_type": "entry_view", "turn": 99},
        {"session_id": _sid(1), "project": "puruma", "event_type": "entry_view", "timestamp": "2026-11-22T00:00:00Z"},
    ]
    for body in bad:
        assert (await client.post("/api/events/track", json=body)).status_code == 422, body
    assert promo_contents()["fridge"] == {} and promo_contents()["cloud"] == {}
    assert PROMO in promo_contents()["puruma"]


async def test_track_rate_limit_per_session(client):
    session = _sid(77)
    for _ in range(65):
        assert (await _track(client, session, "fridge", "story_complete")).status_code == 204
    async with SessionLocal() as db:
        from sqlalchemy import func, select
        saved = await db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.session_id == session))
    assert saved == 60


async def test_access_is_deduplicated_and_sample_is_separated(client, real_server, monkeypatch):
    admin = await _headers(client)
    await _isolate("cloud")
    for _ in range(3):
        await _track(client, _sid(10), "cloud", "entry_view")  # 같은 세션 재진입 → 한 번
    await _track(client, _sid(11), "cloud", "entry_view")
    await _track(client, _sid(11), "fridge", "entry_view")  # 다른 작품은 따로
    monkeypatch.setattr(events_route, "get_llm", lambda: SimpleNamespace(name="mock"))
    await _track(client, _sid(12), "cloud", "entry_view")  # 서버 Mock → 샘플

    real = await _stats(client, admin, "cloud", "real")
    sample = await _stats(client, admin, "cloud", "sample")
    every = await _stats(client, admin, "cloud", "all")
    assert real["access"]["sessions"] == 2 and sample["access"]["sessions"] == 1 and every["access"]["sessions"] == 3
    assert real["events_scope"] == {"real_sessions": 2, "sample_sessions": 1}
    assert real["promo"]["applicable"] is False and real["promo"]["contents"] == []


async def test_promo_impressions_clicks_and_ctr(client, real_server):
    admin = await _headers(client)
    await _isolate("puruma")
    # 세션 1: PROMO 노출(3번 보내도 한 번) + 클릭 2번 / 세션 2: PROMO 노출만 / 세션 3: PROMO2 노출·클릭
    for _ in range(3):
        await _track(client, _sid(21), "puruma", "promo_impression", content_id=PROMO)
    await _track(client, _sid(21), "puruma", "promo_click", content_id=PROMO)
    await _track(client, _sid(21), "puruma", "promo_click", content_id=PROMO)
    await _track(client, _sid(22), "puruma", "promo_impression", content_id=PROMO)
    await _track(client, _sid(23), "puruma", "promo_impression", content_id=PROMO2)
    await _track(client, _sid(23), "puruma", "promo_click", content_id=PROMO2)

    promo = (await _stats(client, admin, "puruma"))["promo"]
    by_id = {c["id"]: c for c in promo["contents"]}
    assert promo["applicable"] is True and set(by_id) == set(promo_contents()["puruma"])
    assert (by_id[PROMO]["impressions"], by_id[PROMO]["clicks"], by_id[PROMO]["click_sessions"], by_id[PROMO]["ctr"]) == (2, 2, 1, 50.0)
    assert (by_id[PROMO2]["impressions"], by_id[PROMO2]["click_sessions"], by_id[PROMO2]["ctr"]) == (1, 1, 100.0)
    assert by_id["rag_dining_cafeteria_menu"]["impressions"] == 0 and by_id["rag_dining_cafeteria_menu"]["ctr"] is None
    assert (promo["impressions"], promo["clicks"], promo["click_sessions"], promo["ctr"]) == (3, 3, 2, round(2 / 3 * 100, 1))
    assert all(c["label"] for c in promo["contents"])


async def test_revisit_rate_is_returning_share_of_completed_visitors(client, real_server):
    admin = await _headers(client)
    await _isolate("fridge")
    # 방문자 A: 세션1 시작·완료 → 같은 세션 다시 하기(재방문 아님) → 세션2 시작(재방문)
    await _track(client, _sid(31), "fridge", "story_start", visitor_id=_vid(1))
    await _track(client, _sid(31), "fridge", "story_complete", visitor_id=_vid(1))
    await _track(client, _sid(31), "fridge", "story_start", visitor_id=_vid(1))
    await _track(client, _sid(32), "fridge", "story_start", visitor_id=_vid(1))
    await _track(client, _sid(33), "fridge", "story_start", visitor_id=_vid(1))  # 여러 번 와도 방문자는 한 명
    # 방문자 B: 세션4 시작·완료만(돌아오지 않음)
    await _track(client, _sid(34), "fridge", "story_start", visitor_id=_vid(2))
    await _track(client, _sid(34), "fridge", "story_complete", visitor_id=_vid(2))
    # 방문자 C: 완료 없이 여러 세션에서 시작 → 분모에 없으므로 재방문율을 100% 위로 올리지 않는다
    for n in (35, 36, 37):
        await _track(client, _sid(n), "fridge", "story_start", visitor_id=_vid(3))
    # 방문자 D: 다른 세션에서 먼저 시작했고, 완료는 그 뒤 → 완료 전 시작은 재방문이 아님
    await _track(client, _sid(38), "fridge", "story_start", visitor_id=_vid(4))
    await _track(client, _sid(39), "fridge", "story_start", visitor_id=_vid(4))
    await _track(client, _sid(39), "fridge", "story_complete", visitor_id=_vid(4))

    revisit = (await _stats(client, admin, "fridge"))["revisit"]
    assert revisit == {"returning_visitors": 1, "completed_visitors": 3, "rate": round(1 / 3 * 100, 1), "visitors": 4}
    assert 0 <= revisit["rate"] <= 100


async def test_csv_contains_only_aggregates_and_follows_permissions(client, real_server):
    admin = await _headers(client)
    await _isolate("cloud")
    await _track(client, _sid(41), "cloud", "entry_view")
    await _track(client, _sid(41), "cloud", "story_start", visitor_id=_vid(41))
    response = await client.get("/api/admin/projects/cloud/stats.csv", params={"days": 7, "data": "real"}, headers=admin)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"] and "mingle-cloud-7d-real" in response.headers["content-disposition"]
    text = response.text
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0] == ["구분", "지표", "항목", "값"]
    values = {(r[0], r[1], r[2]): r[3] for r in rows[1:]}
    assert values[("핵심 지표", "총 접속 수(세션)", "")] == "1"
    assert values[("홍보", "상태", "")] == "해당 없음"
    assert values[("조회 조건", "데이터", "")] == "실제 데이터"
    assert _sid(41) not in text and _vid(41) not in text and "sess-" not in text
    sample_csv = await client.get("/api/admin/projects/cloud/stats.csv", params={"data": "sample"}, headers=admin)
    assert "샘플 데이터(서버 Mock)가 포함" in sample_csv.text

    await provision("csv-owner@cloud", "담당자", PASSWORD, False, ["cloud"])
    owner = await _headers(client, "csv-owner@cloud", PASSWORD)
    assert (await client.get("/api/admin/projects/cloud/stats.csv", headers=owner)).status_code == 200
    for other in ("puruma", "fridge"):
        assert (await client.get(f"/api/admin/projects/{other}/stats.csv", headers=owner)).status_code == 403
    assert (await client.get("/api/admin/projects/cloud/stats.csv")).status_code == 401


async def test_share_stats_are_not_affected_by_track_events(client, real_server):
    admin = await _headers(client)
    before = await _stats(client, admin, "cloud", "all")
    await _track(client, _sid(51), "cloud", "entry_view")
    await _track(client, _sid(51), "cloud", "story_complete", visitor_id=_vid(51))
    assert (await client.post("/api/events/share", json={"anon_id": _sid(51), "project": "cloud", "event": "share_click"})).status_code == 204
    after = await _stats(client, admin, "cloud", "all")
    assert after["share"]["share_clicks"] == before["share"]["share_clicks"] + 1
    assert after["share"]["link_opens"] == before["share"]["link_opens"]
    assert after["chat"] == before["chat"]
    # 공유 엔드포인트는 기존처럼 새 필드를 거부한다.
    assert (await client.post("/api/events/share", json={"anon_id": _sid(51), "project": "cloud", "event": "entry_view"})).status_code == 422
