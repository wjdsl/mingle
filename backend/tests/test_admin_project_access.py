"""관리자 계정의 작품 지정(작품 담당자) 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.base import SessionLocal
from app.db.models import AdminUser
from app.services.admin_access import PROJECT_DASHBOARD_NOT_READY, load_projects, normalize_projects
from scripts.create_admin import provision

PASSWORD = "project-pass-12345"


async def _account(email: str) -> tuple[AdminUser, list[str]]:
    async with SessionLocal() as db:
        admin = (await db.execute(select(AdminUser).where(AdminUser.email == email))).scalar_one()
        return admin, await load_projects(db, admin.id)


def test_normalize_projects_orders_and_rejects_unknown():
    assert normalize_projects(["Fridge", "puruma", "fridge", " "]) == ["puruma", "fridge"]
    assert normalize_projects(None) == []
    with pytest.raises(ValueError):
        normalize_projects(["unknown"])


async def test_project_account_is_created_with_projects(client):
    result = await provision("school@puruma", "학교 담당자", PASSWORD, False, ["fridge", "puruma", "fridge"])
    assert result == ["puruma", "fridge"]
    admin, projects = await _account("school@puruma")
    assert admin.role == "project"
    assert projects == ["puruma", "fridge"]


async def test_platform_account_has_no_projects_and_can_login(client):
    result = await provision("team@mingle", "팀", PASSWORD, False)
    assert result == []
    admin, projects = await _account("team@mingle")
    assert admin.role == "admin"
    assert projects == []
    response = await client.post("/api/admin/login", json={"email": "team@mingle", "password": PASSWORD})
    assert response.status_code == 200, response.text


async def test_project_account_login_is_blocked_until_dashboard_ready(client):
    await provision("viewer@fridge", "담당자", PASSWORD, False, ["fridge"])
    response = await client.post("/api/admin/login", json={"email": "viewer@fridge", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["detail"] == PROJECT_DASHBOARD_NOT_READY


async def test_project_account_token_cannot_read_admin_api(client):
    await provision("token@cloud", "담당자", PASSWORD, False, ["cloud"])
    admin, _ = await _account("token@cloud")
    token = create_access_token(admin.id, {"email": admin.email, "role": admin.role, "name": admin.name})
    for path in ["/me", "/overview", "/conversations", "/triggers"]:
        response = await client.get(f"/api/admin{path}", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, path


async def test_reset_without_project_keeps_project_role(client):
    await provision("keep@puruma", "담당자", PASSWORD, False, ["puruma"])
    result = await provision("keep@puruma", "담당자", "new-password-12345", True)
    assert result == ["puruma"]
    admin, projects = await _account("keep@puruma")
    assert admin.role == "project"
    assert projects == ["puruma"]


async def test_reset_with_project_replaces_projects(client):
    await provision("swap@fridge", "담당자", PASSWORD, False, ["fridge"])
    result = await provision("swap@fridge", "담당자", PASSWORD, True, ["cloud"])
    assert result == ["cloud"]
    _, projects = await _account("swap@fridge")
    assert projects == ["cloud"]


async def test_existing_account_without_reset_is_rejected(client):
    await provision("dup@cloud", "담당자", PASSWORD, False, ["cloud"])
    with pytest.raises(ValueError):
        await provision("dup@cloud", "담당자", PASSWORD, False, ["cloud"])


def test_login_id_does_not_need_email():
    from app.services.admin_access import normalize_login_id

    assert normalize_login_id("  Puruma-School ") == "puruma-school"
    assert normalize_login_id("admin@mingle") == "admin@mingle"  # 기존 이메일 형식도 허용
    for bad in ["ab", "-admin", "관리자", "admin school", "admin/1", ""]:
        with pytest.raises(ValueError):
            normalize_login_id(bad)


async def test_plain_id_account_can_login(client):
    await provision("mingle-team", "팀", PASSWORD, False)
    response = await client.post("/api/admin/login", json={"email": "Mingle-Team", "password": PASSWORD})
    assert response.status_code == 200, response.text
    wrong = await client.post("/api/admin/login", json={"email": "mingle-team", "password": "wrong-password-1"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "아이디 또는 비밀번호가 올바르지 않습니다."
