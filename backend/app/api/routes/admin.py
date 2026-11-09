"""관리자 로그인 / B2B Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.db.base import get_db
from app.db.models import (
    AdminUser,
    CTADef,
    Conversation,
    MarketingEvent,
    MarketingTriggerDef,
    Message,
    Persona,
    RelationshipState,
    UserSession,
)
from app.schemas.admin import (
    AdminOut,
    DashboardOverview,
    LoginRequest,
    RecentConversation,
    TokenOut,
    TriggerStats,
)
from app.services.analytics import build_overview
from app.services.memory import load_notes

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", response_model=TokenOut, summary="관리자 로그인")
async def login(
    payload: LoginRequest, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    admin = (
        await db.execute(
            select(AdminUser).where(AdminUser.email == payload.email.strip().lower())
        )
    ).scalar_one_or_none()
    if admin is None or not admin.is_active or not verify_password(
        payload.password, admin.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    token = create_access_token(
        admin.id, {"email": admin.email, "role": admin.role, "name": admin.name}
    )
    return TokenOut(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        admin=AdminOut.model_validate(admin),
    )


@router.get("/me", response_model=AdminOut, summary="관리자 정보")
async def me(admin: AdminUser = Depends(get_current_admin)):
    return admin


@router.get(
    "/overview",
    response_model=DashboardOverview,
    summary="B2B Dashboard 요약",
)
async def overview(
    days: int = Query(default=14, ge=1, le=90),
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await build_overview(db, days)


@router.get(
    "/conversations",
    response_model=list[RecentConversation],
    summary="최근 대화 목록",
)
async def list_conversations(
    persona_slug: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Conversation, Persona, RelationshipState, UserSession)
        .join(Persona, Persona.id == Conversation.persona_id)
        .outerjoin(RelationshipState, RelationshipState.conversation_id == Conversation.id)
        .join(UserSession, UserSession.id == Conversation.session_id)
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(limit)
    )
    if persona_slug:
        stmt = stmt.where(Persona.slug == persona_slug)
    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter)

    rows = (await db.execute(stmt)).all()
    return [
        RecentConversation(
            conversation_id=conversation.id,
            persona_name=persona.name,
            session_hint=f"****{session.code_hint}" if session.code_hint else "****",
            stage=state.stage if state else "낯섦",
            affinity=state.affinity if state else 0,
            turn_count=state.turn_count if state else 0,
            status=conversation.status,
            last_message_at=conversation.last_message_at,
        )
        for conversation, persona, state, session in rows
    ]


@router.get(
    "/conversations/{conversation_id}",
    summary="대화 상세 (전체 메시지/기억/마케팅 이벤트)",
)
async def conversation_detail(
    conversation_id: str,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    persona = await db.get(Persona, conversation.persona_id)
    state = (
        await db.execute(
            select(RelationshipState).where(
                RelationshipState.conversation_id == conversation.id
            )
        )
    ).scalar_one_or_none()
    messages = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    ).scalars().all()
    notes = await load_notes(db, conversation.session_id, conversation.persona_id)
    events = (
        await db.execute(
            select(MarketingEvent)
            .where(MarketingEvent.conversation_id == conversation.id)
            .order_by(MarketingEvent.created_at)
        )
    ).scalars().all()

    return {
        "id": conversation.id,
        "persona": {
            "id": persona.id,
            "name": persona.name,
            "slug": persona.slug,
            "avatar_emoji": persona.avatar_emoji,
        },
        "title": conversation.title,
        "status": conversation.status,
        "created_at": conversation.created_at,
        "last_message_at": conversation.last_message_at,
        "state": {
            "turn_count": state.turn_count if state else 0,
            "affinity": state.affinity if state else 0,
            "trust": state.trust if state else 0,
            "stage": state.stage if state else "낯섦",
            "chapter": state.chapter if state else 1,
            "flags": state.flags if state else {},
            "ending_code": state.ending_code if state else None,
        },
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "provider": message.provider,
                "latency_ms": message.latency_ms,
                "extra": message.extra,
                "created_at": message.created_at,
            }
            for message in messages
        ],
        "notes": [
            {
                "key": note.key,
                "value": note.value,
                "category": note.category,
                "importance": note.importance,
            }
            for note in notes
        ],
        "marketing_events": [
            {
                "trigger_id": event.trigger_id,
                "cta_id": event.cta_id,
                "event_type": event.event_type,
                "extra": event.extra,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


@router.get(
    "/triggers",
    response_model=list[TriggerStats],
    summary="Marketing Trigger 설정 및 성과",
)
async def list_triggers(
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    triggers = (
        await db.execute(
            select(MarketingTriggerDef, Persona.name)
            .join(Persona, Persona.id == MarketingTriggerDef.persona_id)
            .order_by(Persona.sort_order, MarketingTriggerDef.priority.desc())
        )
    ).all()
    result: list[TriggerStats] = []
    for trigger, persona_name in triggers:
        impressions = int(
            (
                await db.scalar(
                    select(func.count())
                    .select_from(MarketingEvent)
                    .where(
                        MarketingEvent.trigger_id == trigger.id,
                        MarketingEvent.event_type == "impression",
                    )
                )
            )
            or 0
        )
        clicks = int(
            (
                await db.scalar(
                    select(func.count())
                    .select_from(MarketingEvent)
                    .where(
                        MarketingEvent.trigger_id == trigger.id,
                        MarketingEvent.event_type == "click",
                    )
                )
            )
            or 0
        )
        result.append(
            TriggerStats(
                trigger_id=trigger.id,
                code=trigger.code,
                name=trigger.name,
                persona_name=persona_name,
                impressions=impressions,
                clicks=clicks,
                ctr=round(clicks / impressions * 100, 1) if impressions else 0.0,
            )
        )
    return result


@router.get("/triggers/{trigger_id}/config", summary="Trigger 조건/CTA 설정 조회")
async def trigger_config(
    trigger_id: str,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    trigger = await db.get(MarketingTriggerDef, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger를 찾을 수 없습니다.")
    ctas = (
        await db.execute(
            select(CTADef).where(CTADef.trigger_id == trigger.id).order_by(CTADef.sort_order)
        )
    ).scalars().all()
    return {
        "id": trigger.id,
        "code": trigger.code,
        "name": trigger.name,
        "description": trigger.description,
        "conditions": trigger.conditions,
        "priority": trigger.priority,
        "cooldown_turns": trigger.cooldown_turns,
        "max_fires": trigger.max_fires,
        "is_active": trigger.is_active,
        "ctas": [
            {
                "id": cta.id,
                "label": cta.label,
                "description": cta.description,
                "cta_type": cta.cta_type,
                "url": cta.url,
                "payload": cta.payload,
            }
            for cta in ctas
        ],
    }
