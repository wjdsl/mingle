"""채팅 요청/응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.conversation import NoteOut, StateOut


class ClientNote(BaseModel):
    """브라우저 로컬에 저장된 푸르마 기억 1건. 서버는 매 요청마다 다시 검증한다."""

    key: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)
    importance: str = Field(min_length=1, max_length=10)
    created_at_turn: int = Field(default=0, ge=0, le=100000)
    updated_at_turn: int = Field(default=0, ge=0, le=100000)


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1, max_length=2000)
    notes: list[ClientNote] | None = Field(
        default=None,
        max_length=10,
        description=(
            "푸르마 전용 브라우저 로컬 기억 모드. 생략하면 기존 서버 DB 기억 모드, "
            "빈 배열을 포함해 값을 보내면 로컬 모드(서버 user_notes 미사용)."
        ),
    )


class SourceOut(BaseModel):
    title: str
    category: str
    score: float


class CTAOut(BaseModel):
    id: str
    trigger_id: str
    label: str
    description: str
    cta_type: str
    url: str
    payload: dict = {}


class TriggerOut(BaseModel):
    id: str
    code: str
    name: str
    description: str
    cta: CTAOut | None = None


class StoryEventOut(BaseModel):
    code: str
    title: str
    description: str
    narrative: str


class EndingOut(BaseModel):
    code: str
    title: str
    description: str


class ChatResponse(BaseModel):
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    reply: str
    provider: str
    latency_ms: int
    state: StateOut
    sources: list[SourceOut] = []
    triggers: list[TriggerOut] = []
    story_events: list[StoryEventOut] = []
    ending: EndingOut | None = None
    notes_updated: list[NoteOut] = []
    guardrail_triggered: bool = False
    notes: list[ClientNote] | None = Field(
        default=None, description="로컬 기억 모드에서만 갱신된 전체 기억 목록(최대 10개)."
    )


class ChatSafetyResponse(BaseModel):
    """푸르마 위기 입력 응답. 입력은 저장되지 않았고 상태·기억은 그대로이며 LLM을 부르지 않았다."""

    safety_notice: bool = True
    conversation_id: str
    reply: str
    provider: str = "safety"
    state: StateOut
    notes: list[ClientNote] | None = Field(
        default=None, description="로컬 기억 모드에서만: 재검증한 기존 기억 목록(변경 없음)."
    )
