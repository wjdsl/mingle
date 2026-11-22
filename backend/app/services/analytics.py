"""B2B Dashboard 집계."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Conversation,
    MarketingEvent,
    MarketingTriggerDef,
    Message,
    Persona,
    RelationshipState,
    StoryTurnRecord,
    UserSession,
    utcnow,
)
from app.schemas.admin import (
    DailyPoint,
    DashboardOverview,
    PersonaStats,
    RecentConversation,
    Totals,
    TriggerStats,
)
from app.services.puruma_scenes import PURUMA_STORY_SLUG
from app.services.story_scene_sets import scenario_persona_slug
from app.services.story_scenes import PROJECTS

KST = timezone(timedelta(hours=9), name="KST")
DashboardProject = Literal["puruma", "fridge", "cloud"]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _count(db: AsyncSession, stmt) -> int:
    return int((await db.scalar(stmt)) or 0)


async def build_overview(
    db: AsyncSession, days: int = 14, project: DashboardProject | None = None
) -> DashboardOverview:
    now = utcnow()
    # Inclusive KST calendar days, identical across KPI, tables and daily buckets.
    since = (now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=days - 1)).astimezone(timezone.utc)
    persona_query = select(Persona)
    conversation_scope = select(Conversation.id)
    session_times_query = select(UserSession.created_at).where(UserSession.created_at.between(since, now))
    if project is not None:
        slugs = ("puruma", PURUMA_STORY_SLUG)
        if project != "puruma":
            base_slug = PROJECTS[project].persona_slug
            slugs = (base_slug, scenario_persona_slug(base_slug))
        project_personas = Persona.slug.in_(slugs)
        persona_query = persona_query.where(project_personas)
        conversation_scope = conversation_scope.where(
            Conversation.persona_id.in_(select(Persona.id).where(project_personas))
        )

    cohort = conversation_scope.where(Conversation.created_at.between(since, now))
    if project is not None:
        session_times_query = (
            select(func.min(Conversation.created_at))
            .where(Conversation.id.in_(cohort))
            .group_by(Conversation.session_id)
        )
    session_times = (await db.scalars(session_times_query)).all()
    message_activity = and_(
        Message.conversation_id.in_(conversation_scope),
        Message.created_at.between(since, now),
    )
    message_countable = and_(message_activity, Message.role.in_(["user", "assistant"]))
    marketing_activity = and_(
        MarketingEvent.conversation_id.in_(conversation_scope),
        MarketingEvent.created_at.between(since, now),
    )
    scene_counts = (
        select(func.count())
        .select_from(StoryTurnRecord)
        .where(StoryTurnRecord.conversation_id == Conversation.id)
        .correlate(Conversation)
        .scalar_subquery()
    )
    turn_count = func.coalesce(RelationshipState.turn_count, scene_counts)
    sessions_total = len(session_times)
    conversations_total = await _count(db, select(func.count()).select_from(Conversation).where(Conversation.id.in_(cohort)))
    completed_total = await _count(
        db,
        select(func.count()).select_from(Conversation).where(Conversation.status == "completed", Conversation.id.in_(cohort)),
    )
    messages_total = await _count(
        db,
        select(func.count()).select_from(Message).where(message_countable),
    )
    avg_latency = (
        await db.scalar(
            select(func.avg(Message.latency_ms)).where(
                message_activity, Message.role == "assistant", Message.latency_ms.isnot(None)
            )
        )
    ) or 0.0

    impressions_total = await _count(
        db,
        select(func.count())
        .select_from(MarketingEvent)
        .where(MarketingEvent.event_type == "impression", marketing_activity),
    )
    clicks_total = await _count(
        db,
        select(func.count())
        .select_from(MarketingEvent)
        .where(MarketingEvent.event_type == "click", marketing_activity),
    )

    # --- 페르소나별 ---
    personas = (
        await db.execute(persona_query.order_by(Persona.sort_order, Persona.name))
    ).scalars().all()
    persona_stats: list[PersonaStats] = []
    for persona in personas:
        conv_count = await _count(
            db,
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.persona_id == persona.id, Conversation.id.in_(cohort)),
        )
        conv_completed = await _count(
            db,
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.persona_id == persona.id, Conversation.id.in_(cohort),
                Conversation.status == "completed",
            ),
        )
        msg_count = await _count(
            db,
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.persona_id == persona.id,
                message_countable,
            ),
        )
        avg_turns = (
            await db.scalar(
                select(func.avg(turn_count))
                .select_from(Conversation)
                .outerjoin(RelationshipState, Conversation.id == RelationshipState.conversation_id)
                .where(Conversation.persona_id == persona.id, Conversation.id.in_(cohort))
            )
        ) or 0.0
        avg_affinity = (
            await db.scalar(
                select(func.avg(RelationshipState.affinity))
                .select_from(RelationshipState)
                .join(Conversation, Conversation.id == RelationshipState.conversation_id)
                .where(Conversation.persona_id == persona.id, Conversation.id.in_(cohort))
            )
        ) or 0.0
        impressions = await _count(
            db,
            select(func.count())
            .select_from(MarketingEvent)
            .join(Conversation, Conversation.id == MarketingEvent.conversation_id)
            .where(
                Conversation.persona_id == persona.id,
                MarketingEvent.event_type == "impression", marketing_activity,
            ),
        )
        clicks = await _count(
            db,
            select(func.count())
            .select_from(MarketingEvent)
            .join(Conversation, Conversation.id == MarketingEvent.conversation_id)
            .where(
                Conversation.persona_id == persona.id,
                MarketingEvent.event_type == "click", marketing_activity,
            ),
        )
        persona_stats.append(
            PersonaStats(
                persona_id=persona.id,
                slug=persona.slug,
                name=persona.name,
                conversations=conv_count,
                completed=conv_completed,
                messages=msg_count,
                avg_turns=round(float(avg_turns), 1),
                avg_affinity=round(float(avg_affinity), 1),
                trigger_impressions=impressions,
                trigger_clicks=clicks,
            )
        )

    # --- 트리거별 ---
    triggers = (
        await db.execute(
            select(MarketingTriggerDef, Persona.name)
            .join(Persona, Persona.id == MarketingTriggerDef.persona_id)
            .where(Persona.id.in_(persona_query.with_only_columns(Persona.id)))
            .order_by(Persona.sort_order, MarketingTriggerDef.priority.desc())
        )
    ).all()
    trigger_stats: list[TriggerStats] = []
    for trigger, persona_name in triggers:
        impressions = await _count(
            db,
            select(func.count())
            .select_from(MarketingEvent)
            .where(
                MarketingEvent.trigger_id == trigger.id,
                MarketingEvent.event_type == "impression", marketing_activity,
            ),
        )
        clicks = await _count(
            db,
            select(func.count())
            .select_from(MarketingEvent)
            .where(
                MarketingEvent.trigger_id == trigger.id,
                MarketingEvent.event_type == "click", marketing_activity,
            ),
        )
        trigger_stats.append(
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

    # --- 일별 추이 (KST 기준) ---
    bucket: dict[str, DailyPoint] = {}
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).astimezone(KST).date().isoformat()
        bucket[day] = DailyPoint(date=day, sessions=0, conversations=0, messages=0)

    for created_at in session_times:
        key = _as_utc(created_at).astimezone(KST).date().isoformat()
        if key in bucket:
            bucket[key].sessions += 1

    conv_times = (
        await db.execute(select(Conversation.created_at).where(Conversation.id.in_(cohort)))
    ).scalars().all()
    for created_at in conv_times:
        key = _as_utc(created_at).astimezone(KST).date().isoformat()
        if key in bucket:
            bucket[key].conversations += 1

    msg_times = (
        await db.execute(
            select(Message.created_at).where(message_countable)
        )
    ).scalars().all()
    for created_at in msg_times:
        key = _as_utc(created_at).astimezone(KST).date().isoformat()
        if key in bucket:
            bucket[key].messages += 1

    # --- 관계 단계 분포 ---
    stage_rows = (
        await db.execute(
            select(RelationshipState.stage, func.count()).where(RelationshipState.conversation_id.in_(cohort)).group_by(RelationshipState.stage)
        )
    ).all()
    stages = {str(stage): int(count) for stage, count in stage_rows}

    # --- 최근 대화 ---
    recent_rows = (
        await db.execute(
            select(Conversation, Persona, RelationshipState, UserSession.code_hint, turn_count)
            .join(Persona, Persona.id == Conversation.persona_id)
            .outerjoin(
                RelationshipState,
                RelationshipState.conversation_id == Conversation.id,
            )
            .join(UserSession, UserSession.id == Conversation.session_id)
            .where(Conversation.id.in_(cohort))
            .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
            .limit(10)
        )
    ).all()
    recent_conversations = [
        RecentConversation(
            conversation_id=conversation.id,
            persona_name=persona.name,
            session_hint=f"****{code_hint}" if project is None and code_hint else "****",
            stage=state.stage if state else ("낯섦" if project is None else ""),
            affinity=state.affinity if state else 0,
            turn_count=turns,
            status=conversation.status,
            last_message_at=_as_utc(conversation.last_message_at) if conversation.last_message_at else None,
        )
        for conversation, persona, state, code_hint, turns in recent_rows
    ]

    ctr = round(clicks_total / impressions_total * 100, 1) if impressions_total else 0.0
    return DashboardOverview(
        environment=settings.environment,
        generated_at=now,
        range_days=days,
        totals=Totals(
            sessions=sessions_total,
            conversations=conversations_total,
            completed_conversations=completed_total,
            messages=messages_total,
            avg_latency_ms=round(float(avg_latency), 1),
            trigger_impressions=impressions_total,
            trigger_clicks=clicks_total,
            ctr=ctr,
        ),
        personas=persona_stats,
        triggers=trigger_stats,
        daily=list(bucket.values()),
        stages=stages,
        recent_conversations=recent_conversations,
    )
