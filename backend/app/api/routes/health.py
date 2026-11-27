"""헬스체크 / 서비스 정보."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import get_db
from app.db.models import Persona, utcnow
from app.services.llm import degraded_reason, get_llm, is_degraded

router = APIRouter(tags=["system"])


@router.get("/health", summary="헬스체크")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    llm = get_llm()
    persona_count = int(
        (await db.scalar(select(func.count()).select_from(Persona))) or 0
    )
    redis_status = "not_configured"
    if settings.redis_url:
        try:
            import redis.asyncio as _redis

            client = _redis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            await client.aclose()
            redis_status = "ok"
        except Exception as exc:  # pragma: no cover
            redis_status = f"error: {type(exc).__name__}"
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "database": "postgresql" if settings.is_postgres else "sqlite",
        "redis": redis_status,
        "llm": {
            "provider": llm.name,
            "chat_model": llm.chat_model,
            "embedding_dim": settings.embedding_dim,
            "degraded": is_degraded(),
            "degraded_reason": degraded_reason(),
        },
        "personas": persona_count,
        "server_time": utcnow().isoformat(),
    }


@router.get("/metrics", summary="Prometheus 메트릭")
async def metrics() -> Response:
    # 최소한의 프로세스/서비스 메트릭. 상세 계측은 추후 확장.
    body = (
        "# HELP mingle_up 서비스 가동 여부\n"
        "# TYPE mingle_up gauge\n"
        "mingle_up 1\n"
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")
