"""작품별 채팅·공유 통계 집계 (대시보드).

집계 기준
- 기간: KST 달력 기준 오늘 포함 N일.
- 대화 코호트: 기간 안에 시작한(created_at) 작품의 대화. 냉장고·구름섬은 이전 장면 세트(ui_mock_v1)와
  현재 시나리오 세트(scenario_draft_v1)의 페르소나를 모두 같은 작품으로 묶는다.
- 샘플 구분(FR-73): 대화 단위로 판정한다. 저장된 턴(story_turns, 이전 푸르마는 응답 메시지) 중 provider가
  mock인 턴이 하나라도 있으면 샘플 대화다. 고정 연출(fixed)·AI 대체 응답(fallback) 턴은 Mock이 아니다.
  저장된 턴이 없는 대화는 판정할 수 없어 실제 쪽에 넣고 개수를 따로 알린다.
  mode=real(기본)은 샘플을 빼고, sample은 샘플만, all은 둘 다 센다. 공유 이벤트는 대화와 연결되지 않아 구분하지 않는다.
- 진행 턴: 코호트 대화에서 서버에 저장된 턴. 이전 푸르마(/api/chat)는 relationship_states.turn_count,
  장면형 대화는 story_turns 행 수. 실패·위기 안내로 저장되지 않은 입력과 같은 요청 ID의 재시도는 세지 않는다.
- 완료율: 코호트 중 status가 completed인 대화 / 코호트 대화 수(현재 상태 기준).
- 구간 도달률: 현재 장면 세트 대화 중 구간 첫 장면을 받은 대화(저장된 턴 수 >= 구간 시작 턴 번호-1) / 같은 세트 대화.
- 엔딩 분포: 현재 장면 세트의 끝난 대화를 저장된 턴 기록으로 다시 판정한다(story_judgement·puruma_state와 같은 규칙).
- 체류 시간: 저장된 첫 턴 시각 ~ 마지막 턴 시각(근사). 턴 시각이 2개 이상인 대화만.
- 관심 분야: 푸르마 자유 입력 턴에 저장된 주제(topic). 다른 작품은 해당 없음.
- AI 대체 응답 비율: 장면형 턴 중 고정 연출을 뺀 턴에서 provider=fallback인 비율과 사유 코드별 건수.
- 공유: 결과 화면 버튼을 누른 시점의 이벤트 수. 링크 열기·링크로 체험 시작은 별도 지표다.
채팅 원문·호칭·개인 코드는 읽지도 반환하지도 않는다. 메시지 extra에서는 JSON 경로로 분류 값만 꺼낸다.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, Persona, RelationshipState, ShareEvent, StoryTurnRecord, utcnow
from app.schemas.admin import (
    ChatStats,
    DataScope,
    DwellStats,
    EndingCount,
    EndingStats,
    FallbackStats,
    InterestStats,
    ProjectDailyPoint,
    ProjectStats,
    ReasonCount,
    SegmentReach,
    SegmentStats,
    ShareStats,
    TopicCount,
)
from app.services import puruma_state
from app.services.analytics import KST, DashboardProject, _as_utc
from app.services.memory import PURUMA_PERSONA_SLUG
from app.services.puruma_scenes import PURUMA_SCENE_SET, PURUMA_STORY_SLUG, SECTIONS, TOPIC_INTENTS
from app.services.story_data import load_draft
from app.services.story_judgement import (
    CLOUD_CENTER_RESULT,
    CLOUD_QUADRANTS,
    FRIDGE_STAGE_THRESHOLDS,
    JUDGED_SCENE_SET,
    _intent_for,
    judge_cloud,
    judge_fridge,
    score_tables,
)
from app.services.story_scene_sets import scenario_persona_slug
from app.services.story_scenes import PROJECTS

SHARE_EVENTS = ("share_click", "image_save_click", "link_open", "link_start")
DATA_MODES = ("real", "sample", "all")
MOCK_PROVIDER = "mock"
FIXED_PROVIDER = "fixed"
FALLBACK_PROVIDER = "fallback"


def project_persona_slugs(project: DashboardProject) -> tuple[str, ...]:
    if project == "puruma":
        # /api/chat 개강 2턴(기존)과 /api/story-chat 10턴(2026-11-22) 대화를 같은 작품으로 묶는다.
        return (PURUMA_PERSONA_SLUG, PURUMA_STORY_SLUG)
    base = PROJECTS[project].persona_slug
    return (base, scenario_persona_slug(base))


def current_scene_set(project: DashboardProject) -> tuple[str, str]:
    """(현재 장면 세트 이름, 그 세트의 페르소나 slug). 구간·엔딩은 이 세트의 대화만 계산한다."""
    if project == "puruma":
        return PURUMA_SCENE_SET, PURUMA_STORY_SLUG
    return JUDGED_SCENE_SET, scenario_persona_slug(PROJECTS[project].persona_slug)


def segment_defs(project: DashboardProject) -> list[tuple[str, str, int]]:
    """(구간 ID, 이름, 시작 턴 0부터). 푸르마는 puruma_scenes.SECTIONS, 냉장고·구름섬은 장면 카드 초안의 phases."""
    if project == "puruma":
        return [(s.id, s.title, s.turns[0]) for s in SECTIONS]
    draft = load_draft(project) or {}
    return [(p["id"], p["name"], int(p["turn_range"][0]) - 1) for p in draft.get("phases") or []]


def ending_ids(project: DashboardProject) -> tuple[str, ...]:
    if project == "puruma":
        return puruma_state.ENDING_IDS
    if project == "fridge":
        return tuple(f"fridge_rel_stage_{n}" for n in range(1, len(FRIDGE_STAGE_THRESHOLDS) + 2))
    return (*CLOUD_QUADRANTS.values(), CLOUD_CENTER_RESULT)


def range_start(days: int):
    now = utcnow()
    since = (now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=days - 1)).astimezone(timezone.utc)
    return since, now


def _rate(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


def _percentile(values: list[float], q: float) -> int | None:
    """nearest-rank 백분위(초 단위 정수)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return int(round(ordered[rank - 1]))


def _median(values: list[float]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    value = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return int(round(value))


def _judge(project: DashboardProject, turns: list) -> str | None:
    """저장된 턴 행으로 결말을 다시 판정한다(story_judgement.judge_conversation과 같은 규칙, 추가 쿼리 없음)."""
    if project == "puruma":
        views = [puruma_state.TurnView(t.turn_index, t.choice_id, t.topic, t.attitude, t.promo_id, t.path) for t in turns]
        return puruma_state.judge(puruma_state.fold(views))
    tables = score_tables(project)
    if not tables:
        return None
    intents = {t.turn_index: _intent_for(t.turn_index, t.choice_id, t.intent_id, tables) for t in turns}
    return judge_fridge(intents, tables)[0] if project == "fridge" else judge_cloud(intents, tables)[0]


async def build_project_stats(db: AsyncSession, project: DashboardProject, days: int, mode: str = "real") -> ProjectStats:
    if mode not in DATA_MODES:
        raise ValueError(f"unknown data mode: {mode}")
    since, now = range_start(days)
    persona_ids = select(Persona.id).where(Persona.slug.in_(project_persona_slugs(project)))
    cohort = select(Conversation.id).where(Conversation.persona_id.in_(persona_ids), Conversation.created_at.between(since, now))
    cohort_rows = (
        await db.execute(
            select(Conversation.id, Conversation.session_id, Conversation.status, Conversation.created_at, Persona.slug)
            .join(Persona, Persona.id == Conversation.persona_id)
            .where(Conversation.id.in_(cohort))
        )
    ).all()

    # 장면형 턴: 분류 값만 JSON 경로로 꺼낸다(대사 본문·입력 원문은 읽지 않는다).
    extra = Message.extra
    turn_rows = (
        await db.execute(
            select(
                StoryTurnRecord.conversation_id,
                StoryTurnRecord.turn_index,
                StoryTurnRecord.choice_id,
                StoryTurnRecord.provider,
                StoryTurnRecord.created_at,
                extra["intent_id"].as_string().label("intent_id"),
                extra[("story_fallback", "reason")].as_string().label("fallback_reason"),
                extra[("puruma", "topic")].as_string().label("topic"),
                extra[("puruma", "attitude")].as_string().label("attitude"),
                extra[("puruma", "promo_id")].as_string().label("promo_id"),
                extra[("puruma", "path")].as_string().label("path"),
            )
            .outerjoin(Message, Message.id == StoryTurnRecord.assistant_message_id)
            .where(StoryTurnRecord.project == project, StoryTurnRecord.conversation_id.in_(cohort))
            .order_by(StoryTurnRecord.conversation_id, StoryTurnRecord.turn_index)
        )
    ).all()
    turns_of: dict[str, list] = defaultdict(list)
    for row in turn_rows:
        turns_of[row.conversation_id].append(row)

    # 이전 푸르마(/api/chat): 진행 턴은 relationship_states, 샘플 판정·체류 시간은 응답 메시지(인사말 제외).
    legacy_turns: dict[str, int] = {}
    legacy_replies: dict[str, list] = defaultdict(list)
    if project == "puruma":
        legacy_turns = {
            cid: int(count or 0)
            for cid, count in (await db.execute(
                select(RelationshipState.conversation_id, RelationshipState.turn_count)
                .where(RelationshipState.conversation_id.in_(cohort))
            )).all()
        }
        for row in (await db.execute(
            select(Message.conversation_id, Message.provider, Message.created_at).where(
                Message.conversation_id.in_(cohort), Message.role == "assistant",
                Message.provider.is_not(None), Message.provider != "system",
            )
        )).all():
            legacy_replies[row.conversation_id].append(row)

    def providers(cid: str) -> set[str]:
        return {t.provider for t in turns_of.get(cid, [])} | {m.provider for m in legacy_replies.get(cid, [])}

    kinds: dict[str, str] = {}
    for row in cohort_rows:
        seen = providers(row.id)
        kinds[row.id] = "sample" if MOCK_PROVIDER in seen else "real" if seen else "unclassified"
    scope = DataScope(
        mode=mode,
        real_conversations=sum(1 for k in kinds.values() if k == "real"),
        sample_conversations=sum(1 for k in kinds.values() if k == "sample"),
        unclassified_conversations=sum(1 for k in kinds.values() if k == "unclassified"),
    )

    def included(cid: str) -> bool:
        return mode == "all" or (kinds[cid] == "sample") == (mode == "sample")

    rows = [row for row in cohort_rows if included(row.id)]
    ids = [row.id for row in rows]

    def turn_count(cid: str) -> int:
        return len(turns_of[cid]) if turns_of.get(cid) else legacy_turns.get(cid, 0)

    message_counts = dict(
        (await db.execute(
            select(Message.conversation_id, func.count())
            .where(Message.conversation_id.in_(cohort), Message.role.in_(["user", "assistant"]))
            .group_by(Message.conversation_id)
        )).all()
    ) if cohort_rows else {}

    bucket: dict[str, ProjectDailyPoint] = {}
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).astimezone(KST).date().isoformat()
        bucket[day] = ProjectDailyPoint(date=day)
    for row in rows:
        point = bucket.get(_as_utc(row.created_at).astimezone(KST).date().isoformat())
        if point is not None:
            point.conversations += 1
            point.turns += turn_count(row.id)

    conversations = len(rows)
    completed = sum(1 for row in rows if row.status == "completed")
    turns = sum(turn_count(cid) for cid in ids)

    # 구간 도달률·엔딩: 현재 장면 세트 대화만(이전 세트는 구간 정의가 달라 분모에서 뺀다).
    scene_set, current_slug = current_scene_set(project)
    current_rows = [row for row in rows if row.slug == current_slug]
    defs = segment_defs(project)
    segments = SegmentStats(
        scene_set=scene_set,
        conversations=len(current_rows),
        legacy_conversations=conversations - len(current_rows),
        segments=[
            SegmentReach(
                id=seg_id, title=title, start_turn=start + 1,
                reached=(reached := sum(1 for row in current_rows if len(turns_of.get(row.id, [])) >= start)),
                rate=_rate(reached, len(current_rows)),
            )
            for seg_id, title, start in defs
        ],
    )

    ending_counter: Counter[str] = Counter()
    judged = 0
    for row in current_rows:
        if row.status != "completed":
            continue
        ending = _judge(project, turns_of.get(row.id, []))
        if ending:
            judged += 1
            ending_counter[ending] += 1
    endings = EndingStats(
        judged=judged,
        unjudged_completed=completed - judged,
        endings=[EndingCount(id=eid, count=ending_counter[eid], rate=_rate(ending_counter[eid], judged)) for eid in ending_ids(project)],
    )

    durations: list[float] = []
    for cid in ids:
        times = [_as_utc(t.created_at) for t in turns_of.get(cid, [])] or [_as_utc(m.created_at) for m in legacy_replies.get(cid, [])]
        if len(times) >= 2:
            durations.append((max(times) - min(times)).total_seconds())
    dwell = DwellStats(conversations=len(durations), median_seconds=_median(durations), p90_seconds=_percentile(durations, 0.9))

    interest = InterestStats(applicable=project == "puruma")
    if project == "puruma":
        labels = {intent_id: label.split(":")[0] for intent_id, label, _ in TOPIC_INTENTS}
        free = [t for cid in ids for t in turns_of.get(cid, []) if t.choice_id is None and t.provider != FIXED_PROVIDER]
        topic_counter = Counter(t.topic for t in free if t.topic in labels)
        interest.free_inputs = len(free)
        interest.unclassified = len(free) - sum(topic_counter.values())
        interest.topics = [
            TopicCount(id=tid, label=label, count=topic_counter[tid], rate=_rate(topic_counter[tid], len(free)))
            for tid, label in labels.items()
        ]

    llm_turns = [t for cid in ids for t in turns_of.get(cid, []) if t.provider != FIXED_PROVIDER]
    fallback_turns = [t for t in llm_turns if t.provider == FALLBACK_PROVIDER]
    reasons = Counter(t.fallback_reason or "unknown" for t in fallback_turns)
    fallback = FallbackStats(
        llm_turns=len(llm_turns),
        fallback_turns=len(fallback_turns),
        rate=_rate(len(fallback_turns), len(llm_turns)),
        reasons=[ReasonCount(code=code, count=count) for code, count in reasons.most_common()],
    )

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
            sessions=len({row.session_id for row in rows}),
            conversations=conversations,
            completed_conversations=completed,
            completion_rate=_rate(completed, conversations),
            turns=turns,
            avg_turns=round(turns / conversations, 1) if conversations else None,
            messages=sum(int(message_counts.get(cid, 0)) for cid in ids),
        ),
        share=ShareStats(
            share_clicks=counts["share_click"],
            image_save_clicks=counts["image_save_click"],
            link_opens=counts["link_open"],
            link_start_sessions=link_start_sessions,
        ),
        daily=list(bucket.values()),
        scope=scope,
        segments=segments if defs else None,
        endings=endings,
        dwell=dwell,
        interest=interest,
        fallback=fallback,
    )
