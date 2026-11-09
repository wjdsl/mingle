"""비회원 세션 / 개인 코드 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    persona_slug: str | None = Field(
        default=None, description="지정하면 해당 페르소나와의 대화를 바로 생성합니다."
    )


class ResumeRequest(BaseModel):
    personal_code: str = Field(min_length=4, max_length=40)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str | None
    code_hint: str
    created_at: datetime
    last_seen_at: datetime


class SessionCreated(BaseModel):
    session: SessionOut
    personal_code: str = Field(description="이 값은 최초 1회만 반환됩니다. 반드시 저장하세요.")
    conversation: dict | None = None
    conversations: list[dict] = []
