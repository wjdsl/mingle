"""테스트 환경 설정.

- SQLite 임시 DB + Mock LLM 으로 외부 API 없이 전체 흐름을 검증한다.
- 앱 임포트 전에 환경변수를 주입해야 Settings 캐시에 반영된다.
"""

from __future__ import annotations

import os
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent / "test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789-abcdefghij"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["ADMIN_NAME"] = "테스트 관리자"
os.environ["SEED_ON_STARTUP"] = "true"
os.environ["MEMORY_LLM_ENABLED"] = "false"
os.environ["TRIGGER_LLM_JUDGE_ENABLED"] = "false"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.base import engine, init_db  # noqa: E402
from app.db.seed import seed_database  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    await init_db()
    await seed_database()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    await engine.dispose()


@pytest_asyncio.fixture
async def demo_session(client):
    """서하린과의 대화가 준비된 비회원 세션."""
    response = await client.post(
        "/api/sessions",
        json={"display_name": "테스터", "persona_slug": "seo-harin"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return {
        "code": data["personal_code"],
        "headers": {"X-Personal-Code": data["personal_code"]},
        "conversation_id": data["conversation"]["id"],
        "session_id": data["session"]["id"],
    }
