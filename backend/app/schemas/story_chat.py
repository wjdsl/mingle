"""냉장고·구름섬 장면형 스토리 API 스키마 (/api/story-chat)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


SceneSet = Literal["ui_mock_v1", "scenario_draft_v1"]


class StoryConversationCreate(StrictModel):
    project: Literal["fridge", "cloud"]
    scene_set: SceneSet = Field(
        default="ui_mock_v1",
        description="ui_mock_v1: 현재 프론트 Mock 장면(기본). scenario_draft_v1: 시나리오 장면 카드 초안 10턴(팀 미확정).",
    )


class StoryConversationOut(BaseModel):
    conversation_id: str
    project: str
    completed_turns: int
    total_turns: int
    finished: bool
    scene_set: str = "ui_mock_v1"


class StoryTurnInput(StrictModel):
    text: str = Field(min_length=1, max_length=300)
    choice_id: str | None = Field(default=None, max_length=40)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("빈 입력")
        return value


class StoryTurnRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    turn: int = Field(ge=0, le=50, description="0부터 시작하는 장면 번호. 서버 진행 장면과 같아야 한다.")
    input: StoryTurnInput


class StoryFixedTurnRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    turn: int = Field(ge=0, le=50)


class SceneLineOut(BaseModel):
    speaker: str
    text: str
    direction: str | None = None


class SceneChoiceOut(BaseModel):
    choice_id: str
    label: str


class SceneOut(BaseModel):
    turn: int
    title: str
    situation: str
    input_mode: str
    opening_lines: list[SceneLineOut]
    system_messages: list[str]
    choices: list[SceneChoiceOut]
    source_level: str


class SceneSetOut(BaseModel):
    project: str
    scene_set: str
    total_turns: int
    scenes: list[SceneOut]
    note: str


class StoryReplyLine(BaseModel):
    speaker: str
    text: str


class StoryTurnResponse(BaseModel):
    conversation_id: str
    project: str
    request_id: str
    turn: int
    replies: list[StoryReplyLine]
    reaction: str
    provider: str = Field(description="실제 응답을 만든 공급자. mock이면 AI 미연결 고정 응답이다.")
    model: str
    latency_ms: int
    completed_turns: int
    total_turns: int
    finished: bool
    replayed: bool = Field(description="같은 request_id의 저장된 응답을 다시 반환했는지")
    guardrail_triggered: bool = False
    # 하이브리드(냉장고 Qwen 대사) 추적용 추가 필드. 기존 필드 의미는 그대로이며 provider는 스토리 생성 공급자다.
    story_provider: str | None = None
    dialogue_provider: str | None = None
    qwen_used: bool = False
    qwen_latency_ms: int | None = None
    fallback_reason: str | None = None
