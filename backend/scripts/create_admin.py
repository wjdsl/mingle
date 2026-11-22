"""Explicit admin provisioning/reset: python -m scripts.create_admin --email ...

- --project 없이 만들면 플랫폼 관리자(role="admin", 모든 작품).
- --project를 붙이면 작품 담당자(role="project")가 되고 지정한 작품만 볼 수 있다.
  예) --project puruma, 여러 작품은 --project fridge --project cloud
- --reset은 비밀번호를 바꾼다. --project를 함께 주면 작품 목록도 그 값으로 바꾸고,
  주지 않으면 기존 계정 종류와 작품 목록을 그대로 둔다(작품 담당자가 실수로 전체 관리자가 되지 않게).
"""
from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select
from app.core.security import hash_password
from app.db.base import SessionLocal, engine, init_db
from app.db.models import AdminUser
from app.services.admin_access import (
    PLATFORM_ROLE,
    PROJECT_IDS,
    PROJECT_ROLE,
    load_projects,
    normalize_projects,
    replace_projects,
)


async def provision(
    email: str, name: str, password: str, reset: bool, projects: list[str] | None = None
) -> list[str]:
    """계정을 만들거나 재설정하고, 최종 작품 목록을 돌려준다(플랫폼 관리자는 빈 목록)."""
    wanted = normalize_projects(projects)
    await init_db()
    try:
        async with SessionLocal() as db:
            admin = (await db.execute(select(AdminUser).where(AdminUser.email == email))).scalar_one_or_none()
            if admin and not reset:
                raise ValueError("계정이 이미 존재합니다. 변경하려면 --reset을 사용하세요.")
            if admin is None:
                admin = AdminUser(
                    email=email,
                    name=name,
                    password_hash=hash_password(password),
                    role=PROJECT_ROLE if wanted else PLATFORM_ROLE,
                )
                db.add(admin)
                await db.flush()
                await replace_projects(db, admin.id, wanted)
            else:
                admin.password_hash = hash_password(password)
                admin.is_active = True
                if wanted:
                    admin.role = PROJECT_ROLE
                    await replace_projects(db, admin.id, wanted)
                elif admin.role != PROJECT_ROLE:
                    admin.role = PLATFORM_ROLE
            await db.commit()
            return await load_projects(db, admin.id) if admin.role == PROJECT_ROLE else []
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="관리자 계정 발급 (비밀번호는 숨김 입력)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="관리자")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument(
        "--project",
        action="append",
        choices=PROJECT_IDS,
        help="작품 담당자 계정으로 만들고 볼 수 있는 작품을 지정한다(여러 번 사용 가능).",
    )
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email or len(email) > 200:
        parser.error("유효한 이메일을 입력하세요.")
    password = getpass("새 비밀번호 (12자 이상): ")
    if len(password) < 12 or len(password) > 200 or password != getpass("비밀번호 확인: "):
        parser.error("비밀번호 길이 또는 확인 입력이 올바르지 않습니다.")
    try:
        result = asyncio.run(provision(email, args.name, password, args.reset, args.project))
    except ValueError as exc:
        parser.error(str(exc))
    if result:
        print(f"관리자 계정 설정 완료 (작품 담당자: {', '.join(result)})")
    else:
        print("관리자 계정 설정 완료 (플랫폼 관리자: 모든 작품)")
