"""FastAPI 애플리케이션 엔트리포인트."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import routers
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.base import engine, init_db
from app.db.seed import seed_database
from app.services.llm import ensure_llm_ready

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("서비스 시작: %s v%s", settings.app_name, settings.app_version)
    await ensure_llm_ready()
    await init_db()
    if settings.seed_on_startup:
        await seed_database()
    yield
    await engine.dispose()
    logger.info("서비스 종료")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "캐릭터 IP 기반 LLM 페르소나 컴패니언 AI의 백엔드 API.\n\n"
        "- **Persona + RAG** 기반 캐릭터 대화\n"
        "- **User Note** 장기 기억\n"
        "- **상태 기반** 관계·스토리 분기 및 멀티엔딩\n"
        "- **Marketing Trigger / CTA** 연계\n"
        "- **B2B Dashboard** 집계\n\n"
        "비회원 사용자는 `POST /api/sessions` 로 발급받은 개인 코드를 "
        "`X-Personal-Code` 헤더에 담아 인증합니다.\n"
        "관리자는 `POST /api/admin/login` 의 JWT를 `Authorization: Bearer` 로 전달합니다."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)

for router in routers:
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
        "personas": f"{settings.api_prefix}/personas",
    }
