"""데이터베이스 엔진 / 세션 / 초기화."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """테이블 생성. Postgres면 pgvector 확장을 먼저 활성화한다."""
    from app.db import models  # noqa: F401  (메타데이터 등록)

    if settings.is_postgres:
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("데이터베이스 초기화 완료 (%s)", "postgresql" if settings.is_postgres else "sqlite")
