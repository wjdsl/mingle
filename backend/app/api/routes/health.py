"""헬스체크 / 서비스 정보."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
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
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "database": "postgresql" if settings.is_postgres else "sqlite",
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
