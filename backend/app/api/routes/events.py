"""공유 이벤트 수집 (/api/events/share).

익명 세션 ID, 작품 ID, 이벤트 종류만 받는다. 호칭·대화·결과·개인 코드는 받지도 저장하지도 않는다.
로그인이 필요 없는 공개 엔드포인트이므로 입력을 화이트리스트로 제한하고 같은 익명 ID의 남용을 막는다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import ShareEvent, utcnow

router = APIRouter(prefix="/events", tags=["events"])

# 링크를 열거나 그 링크로 시작한 일은 익명 세션·작품당 한 번만 기록한다.
ONCE_PER_SESSION = {"link_open", "link_start"}
MAX_EVENTS_PER_HOUR = 60


class ShareEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anon_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    project: Literal["puruma", "fridge", "cloud"]
    event: Literal["share_click", "image_save_click", "link_open", "link_start"]


@router.post("/share", status_code=status.HTTP_204_NO_CONTENT, summary="공유 버튼·공유 링크 이벤트 기록")
async def record_share_event(payload: ShareEventIn, db: AsyncSession = Depends(get_db)) -> Response:
    if payload.event in ONCE_PER_SESSION:
        exists = await db.scalar(
            select(ShareEvent.id).where(
                ShareEvent.anon_id == payload.anon_id,
                ShareEvent.project == payload.project,
                ShareEvent.event_type == payload.event,
            ).limit(1)
        )
        if exists:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    recent = await db.scalar(
        select(func.count()).select_from(ShareEvent).where(
            ShareEvent.anon_id == payload.anon_id,
            ShareEvent.created_at >= utcnow() - timedelta(hours=1),
        )
    )
    if int(recent or 0) < MAX_EVENTS_PER_HOUR:
        db.add(ShareEvent(anon_id=payload.anon_id, project=payload.project, event_type=payload.event))
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
