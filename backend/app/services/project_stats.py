"""작품별 채팅·공유 통계 집계 (대시보드).

집계 기준
- 기간: KST 달력 기준 오늘 포함 N일.
- 대화 코호트: 기간 안에 시작한(created_at) 작품의 대화. 냉장고·구름섬은 이전 장면 세트(ui_mock_v1)와
  현재 시나리오 세트(scenario_draft_v1)의 페르소나를 모두 같은 작품으로 묶는다.
- 진행 턴: 코호트 대화에서 서버에 저장된 턴. 푸르마는 relationship_states.turn_count,
  냉장고·구름섬은 story_turns 행 수. 실패·위기 안내로 저장되지 않은 입력과 같은 요청 ID의 재시도는 세지 않는다.
- 완료율: 코호트 중 status가 completed인 대화 / 코호트 대화 수(현재 상태 기준).
- 공유: 결과 화면 버튼을 누른 시점의 이벤트 수. 링크 열기·링크로 체험 시작은 별도 지표다.
채팅 원문·호칭·개인 코드는 읽지도 반환하지도 않는다.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, Persona, RelationshipState, ShareEvent, StoryTurnRecord, utcnow
from app.schemas.admin import ChatStats, ProjectDailyPoint, ProjectStats, ShareStats
from app.services.analytics import KST, DashboardProject, _as_utc
from app.services.memory import PURUMA_PERSONA_SLUG
from app.services.puruma_scenes import PURUMA_STORY_SLUG
from app.services.story_scene_sets import scenario_persona_slug
from app.services.story_scenes import PROJECTS

SHARE_EVENTS = ("share_click", "image_save_click", "link_open", "link_start")


def project_persona_slugs(project: DashboardProject) -> tuple[str, ...]:
    if project == "puruma":
        # /api/chat 개강 2턴(기존)과 /api/story-chat 10턴(2026-11-22) 대화를 같은 작품으로 묶는다.
        return (PURUMA_PERSONA_SLUG, PURUMA_STORY_SLUG)
    base = PROJECTS[project].persona_slug
    return (base, scenario_persona_slug(base))


def range_start(days: int):
    now = utcnow()
    since = (now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=days - 1)).astimezone(timezone.utc)
    return since, now


async def build_project_stats(db: AsyncSession, project: DashboardProject, days: int) -> ProjectStats:
    since, now = range_start(days)
    persona_ids = select(Persona.id).where(Persona.slug.in_(project_persona_slugs(project)))
    cohort_rows = (
        await db.execute(
            select(Conversation.id, Conversation.session_id, Conversation.status, Conversation.created_at)
            .where(Conversation.persona_id.in_(persona_ids), Conversation.created_at.between(since, now))
        )
    ).all()
    cohort_ids = [row.id for row in cohort_rows]

    turns_by_conversation: dict[str, int] = {}
    if cohort_ids:
        if project == "puruma":
            query = select(RelationshipState.conversation_id, RelationshipState.turn_count).where(
                RelationshipState.conversation_id.in_(select(Conversation.id).where(
                    Conversation.persona_id.in_(persona_ids), Conversation.created_at.between(since, now)))
            )
            turns_by_conversation = {cid: int(count or 0) for cid, count in (await db.execute(query)).all()}
            # 10턴 장면형 대화는 relationship_states가 없고 story_turns 행 수로 센다.
            story_query = (
                select(StoryTurnRecord.conversation_id, func.count())
                .where(StoryTurnRecord.project == project, StoryTurnRecord.conversation_id.in_(cohort_ids))
                .group_by(StoryTurnRecord.conversation_id)
            )
            turns_by_conversation.update({cid: int(count) for cid, count in (await db.execute(story_query)).all()})
        else:
            query = (
                select(StoryTurnRecord.conversation_id, func.count())
                .where(
                    StoryTurnRecord.project == project,
                    StoryTurnRecord.conversation_id.in_(select(Conversation.id).where(
                        Conversation.persona_id.in_(persona_ids), Conversation.created_at.between(since, now))),
                )
                .group_by(StoryTurnRecord.conversation_id)
            )
            turns_by_conversation = {cid: int(count) for cid, count in (await db.execute(query)).all()}
        messages = int(
            (
                await db.scalar(
                    select(func.count()).select_from(Message).where(
                        Message.conversation_id.in_(select(Conversation.id).where(
                            Conversation.persona_id.in_(persona_ids), Conversation.created_at.between(since, now))),
                        Message.role.in_(["user", "assistant"]),
                    )
                )
            ) or 0
        )
    else:
        messages = 0

    bucket: dict[str, ProjectDailyPoint] = {}
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).astimezone(KST).date().isoformat()
        bucket[day] = ProjectDailyPoint(date=day)
    for row in cohort_rows:
        point = bucket.get(_as_utc(row.created_at).astimezone(KST).date().isoformat())
        if point is not None:
            point.conversations += 1
            point.turns += turns_by_conversation.get(row.id, 0)

    conversations = len(cohort_rows)
    completed = sum(1 for row in cohort_rows if row.status == "completed")
    turns = sum(turns_by_conversation.get(cid, 0) for cid in cohort_ids)

    counts = {kind: 0 for kind in SHARE_EVENTS}
    for kind, count in (
        await db.execute(
            select(ShareEvent.event_type, func.count()).where(
                ShareEvent.project == project, ShareEvent.created_at.between(since, now)
            ).group_by(ShareEvent.event_type)
        )
    ).all():
        counts[kind] = int(count)
    link_start_sessions = int(
        (
            await db.scalar(
                select(func.count(func.distinct(ShareEvent.anon_id))).where(
                    ShareEvent.project == project,
                    ShareEvent.event_type == "link_start",
                    ShareEvent.created_at.between(since, now),
                )
            )
        ) or 0
    )

    return ProjectStats(
        project=project,
        range_days=days,
        generated_at=now,
        chat=ChatStats(
            sessions=len({row.session_id for row in cohort_rows}),
            conversations=conversations,
            completed_conversations=completed,
            completion_rate=round(completed / conversations * 100, 1) if conversations else None,
            turns=turns,
            avg_turns=round(turns / conversations, 1) if conversations else None,
            messages=messages,
        ),
        share=ShareStats(
            share_clicks=counts["share_click"],
            image_save_clicks=counts["image_save_click"],
            link_opens=counts["link_open"],
            link_start_sessions=link_start_sessions,
        ),
        daily=list(bucket.values()),
    )
