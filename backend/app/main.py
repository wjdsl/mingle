"""FastAPI 애플리케이션 엔트리포인트."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import routers
from app.core.config import settings
from app.core.logging import configure_failure_log, configure_logging
from app.db.base import engine
from app.services.llm import ensure_llm_ready

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    configure_failure_log(settings.llm_failure_log_file)
    logger.info("서비스 시작: %s v%s", settings.app_name, settings.app_version)
    if settings.llm_probe_on_startup:
        await ensure_llm_ready()
    # 테이블 생성/시드는 Alembic 마이그레이션과 별도 명령으로 수행한다.
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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response

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
