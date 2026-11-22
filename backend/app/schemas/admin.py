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
