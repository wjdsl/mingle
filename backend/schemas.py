from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnInput(StrictModel):
    kind: Literal["choice", "text"]
    text: str = Field(min_length=1, max_length=300)
    choiceId: Optional[str] = Field(default=None, max_length=20)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("빈 입력")
        return value.strip()


class HistoryMessage(StrictModel):
    role: Literal["character", "user"]
    text: str = Field(min_length=1, max_length=2000)


CHOICES = [
    {"map": "지도 같이 보자", "ask": "사람들한테 물어보자", "guide": "내가 데려다줄게"},
    {"quiet": "천천히, 조용히 들어가자", "cheer": "괜찮아, 내가 옆에 있잖아", "greet": "인사하고 들어가자"},
]


class TurnRequest(StrictModel):
    requestId: str = Field(min_length=1, max_length=100)
    turn: Literal[1, 2]
    input: TurnInput
    history: list[HistoryMessage] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_turn(self):
        if self.input.kind == "choice":
            label = CHOICES[self.turn - 1].get(self.input.choiceId)
            if label is None or label != self.input.text:
                raise ValueError("현재 턴의 선택지가 아닙니다")
        elif self.input.choiceId is not None:
            raise ValueError("자유 입력에는 선택 ID를 사용할 수 없습니다")
        expected = ["character"] if self.turn == 1 else ["character", "user", "character"]
        if [message.role for message in self.history] != expected:
            raise ValueError("대화 맥락이 현재 턴과 맞지 않습니다")
        return self


class TurnResponse(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    emotion: Literal["confused", "happy", "sparkle"]

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("빈 응답")
        return value.strip()
