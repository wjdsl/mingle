"""관리자 로그인 / B2B Dashboard 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=4, max_length=200)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: str
    projects: list[str] = Field(default_factory=list)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    admin: AdminOut


class Totals(BaseModel):
    sessions: int
    conversations: int
    completed_conversations: int
    messages: int
    avg_latency_ms: float
    trigger_impressions: int
    trigger_clicks: int
    ctr: float


class PersonaStats(BaseModel):
    persona_id: str
    slug: str
    name: str
    conversations: int
    completed: int
    messages: int
    avg_turns: float
    avg_affinity: float
    trigger_impressions: int
    trigger_clicks: int


class TriggerStats(BaseModel):
    trigger_id: str
    code: str
    name: str
    persona_name: str
    impressions: int
    clicks: int
    ctr: float


class DailyPoint(BaseModel):
    date: str
    sessions: int
    conversations: int
    messages: int


class RecentConversation(BaseModel):
    conversation_id: str
    persona_name: str
    session_hint: str
    stage: str
    affinity: int
    turn_count: int
    status: str
    last_message_at: datetime | None = None


class DashboardOverview(BaseModel):
    environment: str = "unknown"
    generated_at: datetime
    range_days: int
    totals: Totals
    personas: list[PersonaStats]
    triggers: list[TriggerStats]
    daily: list[DailyPoint]
    stages: dict[str, int]
    recent_conversations: list[RecentConversation]


class ChatStats(BaseModel):
    sessions: int
    conversations: int
    completed_conversations: int
    completion_rate: float | None = None
    turns: int
    avg_turns: float | None = None
    messages: int


class ShareStats(BaseModel):
    share_clicks: int
    image_save_clicks: int
    link_opens: int
    link_start_sessions: int


class ProjectDailyPoint(BaseModel):
    date: str
    conversations: int = 0
    turns: int = 0


class DataScope(BaseModel):
    """샘플(서버 Mock) 구분. 기간 안 대화를 모드와 무관하게 센다(FR-73)."""

    mode: str = "real"  # real | sample | all
    real_conversations: int = 0
    sample_conversations: int = 0
    unclassified_conversations: int = 0  # 저장된 턴이 없어 샘플 여부를 알 수 없음(실제 쪽에 포함)


class SegmentReach(BaseModel):
    id: str
    title: str
    start_turn: int  # 1부터
    reached: int
    rate: float | None = None


class SegmentStats(BaseModel):
    scene_set: str
    conversations: int = 0  # 분모: 현재 장면 세트로 시작한 대화
    legacy_conversations: int = 0  # 이전 장면 세트·이전 푸르마 대화(구간 정의가 달라 제외)
    segments: list[SegmentReach] = Field(default_factory=list)


class EndingCount(BaseModel):
    id: str
    count: int
    rate: float | None = None


class EndingStats(BaseModel):
    judged: int = 0  # 분모: 끝난 대화 중 판정 대상(현재 장면 세트)
    unjudged_completed: int = 0  # 끝났지만 판정 대상이 아닌 대화(이전 장면 세트 등)
    endings: list[EndingCount] = Field(default_factory=list)


class DwellStats(BaseModel):
    conversations: int = 0  # 턴 시각이 2개 이상인 대화
    median_seconds: int | None = None
    p90_seconds: int | None = None


class TopicCount(BaseModel):
    id: str
    label: str
    count: int
    rate: float | None = None


class InterestStats(BaseModel):
    applicable: bool = False  # 주제 분류가 저장되는 작품(푸르마)만 True
    free_inputs: int = 0
    unclassified: int = 0  # 자유 입력이지만 주제가 저장되지 않은 턴(AI 대체 응답·Mock)
    topics: list[TopicCount] = Field(default_factory=list)


class ReasonCount(BaseModel):
    code: str
    count: int


class FallbackStats(BaseModel):
    llm_turns: int = 0  # AI가 응답해야 했던 턴(고정 연출 제외)
    fallback_turns: int = 0
    rate: float | None = None
    reasons: list[ReasonCount] = Field(default_factory=list)


class EventScope(BaseModel):
    """2차 이벤트(접속·홍보·재방문)의 샘플 구분. 서버 Mock으로 동작 중에 받은 이벤트가 샘플이다."""

    real_sessions: int = 0
    sample_sessions: int = 0


class AccessStats(BaseModel):
    sessions: int = 0  # 작품 시작 화면에 들어온 익명 세션 수(재진입은 한 번)


class PromoContentStats(BaseModel):
    id: str
    label: str
    impressions: int = 0  # 노출된 세션 수(세션·콘텐츠당 한 번)
    clicks: int = 0  # 클릭 횟수(같은 세션의 반복 클릭 포함)
    click_sessions: int = 0  # 클릭한 세션 수
    ctr: float | None = None  # 클릭한 세션 / 노출된 세션


class PromoStats(BaseModel):
    applicable: bool = False  # 확인된 홍보 콘텐츠가 있는 작품만 True
    impressions: int = 0
    clicks: int = 0
    click_sessions: int = 0
    ctr: float | None = None
    contents: list[PromoContentStats] = Field(default_factory=list)


class RevisitStats(BaseModel):
    """재방문율: 완료한 방문자 중 첫 완료 뒤 다른 세션에서 다시 시작한 방문자 비율(0~100%)."""

    returning_visitors: int = 0  # 완료 뒤 다른 세션에서 다시 시작한 방문자
    completed_visitors: int = 0  # 기간 안에 완료한 방문자
    rate: float | None = None
    visitors: int = 0  # 기간 안에 시작한 익명 방문자(브라우저) 수


class ProjectStats(BaseModel):
    project: str
    range_days: int
    generated_at: datetime
    chat: ChatStats
    share: ShareStats
    daily: list[ProjectDailyPoint]
    scope: DataScope = Field(default_factory=DataScope)
    segments: SegmentStats | None = None
    endings: EndingStats = Field(default_factory=EndingStats)
    dwell: DwellStats = Field(default_factory=DwellStats)
    interest: InterestStats = Field(default_factory=InterestStats)
    fallback: FallbackStats = Field(default_factory=FallbackStats)
    events_scope: EventScope = Field(default_factory=EventScope)
    access: AccessStats = Field(default_factory=AccessStats)
    promo: PromoStats = Field(default_factory=PromoStats)
    revisit: RevisitStats = Field(default_factory=RevisitStats)
