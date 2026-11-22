"""공유 이벤트 수집 (/api/events/share)과 대시보드 통계 이벤트 수집 (/api/events/track).

익명 세션 ID, 작품 ID, 이벤트 종류만 받는다. 호칭·대화·결과·개인 코드는 받지도 저장하지도 않는다.
로그인이 필요 없는 공개 엔드포인트이므로 입력을 화이트리스트로 제한하고 같은 익명 ID의 남용을 막는다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import AnalyticsEvent, ShareEvent, utcnow
from app.services import analytics_events as rules
from app.services.llm import get_llm

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


ANON_PATTERN = r"^[A-Za-z0-9-]{8,64}$"


class TrackEventIn(BaseModel):
    """기획서 7장 이벤트 필드. timestamp는 서버가 붙인다. 그 밖의 필드는 422."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=ANON_PATTERN, description="브라우저 탭 단위 무작위 익명 ID")
    visitor_id: str | None = Field(
        default=None, pattern=ANON_PATTERN, description="브라우저에 오래 남는 무작위 익명 ID. 체험 시작·완료에만 보낸다(재방문율)"
    )
    project: Literal["puruma", "fridge", "cloud"]
    event_type: Literal["entry_view", "story_start", "story_complete", "promo_impression", "promo_click"]
    section: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,40}$")
    turn: int | None = Field(default=None, ge=0, le=50)
    content_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,80}$")


@router.post("/track", status_code=status.HTTP_204_NO_CONTENT, summary="대시보드 통계 이벤트 기록")
async def record_track_event(payload: TrackEventIn, db: AsyncSession = Depends(get_db)) -> Response:
    promo = payload.event_type in rules.PROMO_EVENTS
    if promo != (payload.content_id is not None) or (promo and not rules.allowed_content(payload.project, payload.content_id)):
        raise HTTPException(status_code=422, detail="허용되지 않은 콘텐츠 ID입니다.")
    if (payload.visitor_id is not None) and payload.event_type not in rules.VISITOR_EVENTS:
        raise HTTPException(status_code=422, detail="이 이벤트에는 visitor_id를 보내지 않습니다.")
    if payload.event_type in rules.ONCE_PER_SESSION:
        exists = await db.scalar(
            select(AnalyticsEvent.id).where(
                AnalyticsEvent.session_id == payload.session_id,
                AnalyticsEvent.project == payload.project,
                AnalyticsEvent.event_type == payload.event_type,
                AnalyticsEvent.content_id.is_(None) if payload.content_id is None else AnalyticsEvent.content_id == payload.content_id,
            ).limit(1)
        )
        if exists:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    recent = await db.scalar(
        select(func.count()).select_from(AnalyticsEvent).where(
            AnalyticsEvent.session_id == payload.session_id,
            AnalyticsEvent.created_at >= utcnow() - timedelta(hours=1),
        )
    )
    if int(recent or 0) < rules.MAX_EVENTS_PER_HOUR:
        db.add(AnalyticsEvent(
            session_id=payload.session_id,
            visitor_id=payload.visitor_id,
            project=payload.project,
            event_type=payload.event_type,
            section=payload.section,
            turn=payload.turn,
            content_id=payload.content_id,
            # 서버 Mock으로 동작 중이면 샘플(FR-73). 대화가 mock 턴이면 샘플인 1차 기준과 같은 조건이다.
            sample=get_llm().name == "mock",
        ))
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
