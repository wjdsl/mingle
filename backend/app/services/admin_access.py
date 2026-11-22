"""관리자 계정 종류와 작품별 접근 범위.

- role="admin": 플랫폼 관리자(밍글 팀). 모든 작품을 본다. 작품 목록을 두지 않는다.
- role="project": 작품 담당자. admin_project_access에 적힌 작품만 볼 수 있다.

작품별로 걸러진 대시보드는 아직 없으므로, 작품 담당자는 로그인·관리자 API에서 거부한다.
작품 필터와 권한 검사가 구현되면 그때 허용한다.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminProjectAccess

PLATFORM_ROLE = "admin"
PROJECT_ROLE = "project"

# 프론트 작품 ID(#/project/<id>)와 같은 값을 쓴다.
PROJECT_IDS: tuple[str, ...] = ("puruma", "fridge", "cloud")

PROJECT_DASHBOARD_NOT_READY = "작품 담당자용 대시보드는 아직 준비 중입니다. 밍글 팀에 문의해 주세요."


def normalize_projects(projects: list[str] | None) -> list[str]:
    """중복을 없애고 순서를 PROJECT_IDS 기준으로 맞춘다. 모르는 작품 ID는 ValueError."""
    if not projects:
        return []
    cleaned = {p.strip().lower() for p in projects if p and p.strip()}
    unknown = sorted(cleaned - set(PROJECT_IDS))
    if unknown:
        raise ValueError(f"알 수 없는 작품입니다: {', '.join(unknown)} (가능: {', '.join(PROJECT_IDS)})")
    return [p for p in PROJECT_IDS if p in cleaned]


async def load_projects(db: AsyncSession, admin_id: str) -> list[str]:
    rows = (
        await db.execute(select(AdminProjectAccess.project_id).where(AdminProjectAccess.admin_id == admin_id))
    ).scalars().all()
    return [p for p in PROJECT_IDS if p in set(rows)]


async def replace_projects(db: AsyncSession, admin_id: str, projects: list[str]) -> None:
    """계정의 작품 목록을 통째로 바꾼다. 빈 목록이면 모두 지운다. commit은 호출부가 한다."""
    await db.execute(delete(AdminProjectAccess).where(AdminProjectAccess.admin_id == admin_id))
    for project_id in normalize_projects(projects):
        db.add(AdminProjectAccess(admin_id=admin_id, project_id=project_id))
