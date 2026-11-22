"""관리자 계정의 작품 지정(작품 담당자) 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.base import SessionLocal
from app.db.models import AdminUser
from app.services.admin_access import load_projects, normalize_projects
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


async def test_project_account_can_login_and_sees_only_assigned_projects(client):
    await provision("viewer@fridge", "담당자", PASSWORD, False, ["fridge"])
    response = await client.post("/api/admin/login", json={"email": "viewer@fridge", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["admin"]["role"] == "project"
    assert response.json()["admin"]["projects"] == ["fridge"]


async def test_project_account_token_cannot_read_platform_wide_admin_api(client):
    await provision("token@cloud", "담당자", PASSWORD, False, ["cloud"])
    admin, _ = await _account("token@cloud")
    token = create_access_token(admin.id, {"email": admin.email, "role": admin.role, "name": admin.name})
    headers = {"Authorization": f"Bearer {token}"}
    for path in ["/overview", "/overview?project=cloud", "/conversations", "/conversations/x", "/triggers", "/triggers/x/config"]:
        response = await client.get(f"/api/admin{path}", headers=headers)
        assert response.status_code == 403, path
    assert (await client.get("/api/admin/me", headers=headers)).status_code == 200


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
