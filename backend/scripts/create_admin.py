"""Explicit admin provisioning/reset: python -m scripts.create_admin --email ..."""
from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select
from app.core.security import hash_password
from app.db.base import SessionLocal, engine, init_db
from app.db.models import AdminUser


async def provision(email: str, name: str, password: str, reset: bool) -> None:
    await init_db()
    try:
        async with SessionLocal() as db:
            admin = (await db.execute(select(AdminUser).where(AdminUser.email == email))).scalar_one_or_none()
            if admin and not reset:
                raise ValueError("계정이 이미 존재합니다. 변경하려면 --reset을 사용하세요.")
            if admin is None:
                admin = AdminUser(email=email, name=name, password_hash=hash_password(password), role="admin")
                db.add(admin)
            else:
                admin.password_hash = hash_password(password)
                admin.role = "admin"
                admin.is_active = True
            await db.commit()
        print("관리자 계정 설정 완료")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="관리자 계정 발급 (비밀번호는 숨김 입력)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="관리자")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email or len(email) > 200:
        parser.error("유효한 이메일을 입력하세요.")
    password = getpass("새 비밀번호 (12자 이상): ")
    if len(password) < 12 or len(password) > 200 or password != getpass("비밀번호 확인: "):
        parser.error("비밀번호 길이 또는 확인 입력이 올바르지 않습니다.")
    try:
        asyncio.run(provision(email, args.name, password, args.reset))
    except ValueError as exc:
        parser.error(str(exc))
