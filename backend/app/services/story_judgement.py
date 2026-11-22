"""냉장고·구름섬 결말 판정 (기획 결정 2026-11-22).

- 대화 중에는 호칭·단계를 바꾸지 않고, 마지막 장면에서만 결과를 정한다.
- 점수는 장면 카드 초안 JSON의 choice_score_changes 값을 쓴다. 판정 기준은 시나리오 문서의 제안값을 기획이 확정했다.
  · 냉장고: 1~9턴 의도 점수 합, 5점 이하 1단계 / 6~11점 2단계 / 12점 이상 3단계
  · 구름섬: 2~9턴 두 축(관계·공감 - ↔ 목표·효율 +, 안정·안전 - ↔ 도전·변화 +) 누적.
    균형형(두두)은 두 축을 각각 0 쪽으로 2씩 당긴다(0을 넘지 않음).
    두 축이 모두 -1~+1이면 두두, 아니면 부호로 토토(+,+)·비비(+,-)·나나(-,-)·키키(-,+).
    한 축이 0이면 9턴 선택의 그 축 방향을 따르고, 9턴이 균형형·무효면 + 쪽.
- 의도: 버튼이면 버튼에 연결된 의도, 자유 입력이면 LLM이 분류해 저장한 intent_id. 없거나 모르는 의도는 0점.
- 점수 합산·판정은 코드가 한다(SRS FR-25). LLM은 의도 분류만 한다. 점수는 화면에 보내지 않고 결말 ID만 보낸다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, StoryTurnRecord
from app.services.story_data import load_draft, load_official

JUDGED_SCENE_SET = "scenario_draft_v1"
FRIDGE_STAGE_THRESHOLDS = (6, 12)  # 6점 이상 2단계, 12점 이상 3단계
CLOUD_CENTER = 1  # 두 축 모두 |값| <= 1 이면 두두
CLOUD_QUADRANTS = {(1, 1): "cloud_result_toto", (1, -1): "cloud_result_bibi", (-1, -1): "cloud_result_nana", (-1, 1): "cloud_result_kiki"}
CLOUD_CENTER_RESULT = "cloud_result_dudu"


@dataclass(frozen=True, slots=True)
class TurnScores:
    """한 턴의 의도별 점수. fridge는 int, cloud는 (x, y) 또는 'pull'(균형형 당기기 크기)."""

    values: dict[str, Any]
    choices: dict[str, str]  # choice_id -> intent_id


@lru_cache(maxsize=4)
def score_tables(project_id: str) -> dict[int, TurnScores] | None:
    """turn_index(0부터) -> 점수표. 데이터가 없으면 None."""
    draft = load_draft(project_id)
    if draft is None:
        return None
    tables: dict[int, TurnScores] = {}
    for slot in draft.get("turn_slots", []):
        values: dict[str, Any] = {}
        for v in (slot.get("choice_score_changes") or {}).get("values") or []:
            if "value" in v:
                values[v["intent_id"]] = int(v["value"])
            elif "balance_pull_toward_zero_per_axis" in v:
                values[v["intent_id"]] = ("pull", int(v["balance_pull_toward_zero_per_axis"]))
            elif "relationship_goal" in v and "stability_challenge" in v:
                values[v["intent_id"]] = (int(v["relationship_goal"]), int(v["stability_challenge"]))
        choices = {c["choice_id"]: c["intent_id"] for c in (slot.get("fixed_choices") or []) if c.get("choice_id") and c.get("intent_id")}
        tables[int(slot["turn_number"]) - 1] = TurnScores(values, choices)
    return tables


def judge_fridge(intents: dict[int, str | None], tables: dict[int, TurnScores]) -> tuple[str, int]:
    total = 0
    for turn, intent in intents.items():
        value = tables.get(turn, TurnScores({}, {})).values.get(intent or "")
        if isinstance(value, int):
            total += value
    stage = 1 + sum(total >= t for t in FRIDGE_STAGE_THRESHOLDS)
    return f"fridge_rel_stage_{stage}", total


def _pull(value: int, amount: int) -> int:
    return max(value - amount, 0) if value > 0 else min(value + amount, 0)


def _sign(value: int) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def judge_cloud(intents: dict[int, str | None], tables: dict[int, TurnScores]) -> tuple[str, int, int]:
    x = y = 0
    last_direction = (1, 1)  # 9턴이 균형형·무효면 + 쪽
    last_turn = max(tables) - 1 if tables else 8  # 마지막 입력 장면(예고편 직전)
    for turn in sorted(intents):
        value = tables.get(turn, TurnScores({}, {})).values.get(intents[turn] or "")
        if isinstance(value, tuple) and value and value[0] == "pull":
            x, y = _pull(x, value[1]), _pull(y, value[1])
            direction = None
        elif isinstance(value, tuple) and len(value) == 2:
            x, y = x + value[0], y + value[1]
            direction = (_sign(value[0]) or 1, _sign(value[1]) or 1)
        else:
            direction = None
        if turn == last_turn:
            last_direction = direction or (1, 1)
    if abs(x) <= CLOUD_CENTER and abs(y) <= CLOUD_CENTER:
        return CLOUD_CENTER_RESULT, x, y
    key = (_sign(x) or last_direction[0], _sign(y) or last_direction[1])
    return CLOUD_QUADRANTS[key], x, y


def _intent_for(turn: int, choice_id: str | None, llm_intent: str | None, tables: dict[int, TurnScores]) -> str | None:
    table = tables.get(turn)
    if table is None:
        return None
    if choice_id:
        return table.choices.get(choice_id)
    return llm_intent if llm_intent in table.values else None


async def turn_intents(db: AsyncSession, conversation: Conversation, tables: dict[int, TurnScores]) -> dict[int, str | None]:
    rows = (
        await db.execute(
            select(StoryTurnRecord.turn_index, StoryTurnRecord.choice_id, StoryTurnRecord.assistant_message_id)
            .where(StoryTurnRecord.conversation_id == conversation.id)
            .order_by(StoryTurnRecord.turn_index)
        )
    ).all()
    message_ids = [r.assistant_message_id for r in rows]
    extras = {}
    if message_ids:
        extras = {m.id: (m.extra or {}) for m in (await db.execute(select(Message).where(Message.id.in_(message_ids)))).scalars()}
    return {r.turn_index: _intent_for(r.turn_index, r.choice_id, extras.get(r.assistant_message_id, {}).get("intent_id"), tables) for r in rows}


def fridge_trailer_text(ending_id: str | None) -> str | None:
    """관계 단계별 10턴 마무리 대사(공식 fridge_trailer_cuts.json, 바이블 가안). [호칭]은 호출부가 채운다."""
    official = load_official("fridge")
    if official is None or not ending_id:
        return None
    variants = official.get("trailer").get("relationship_variants") or []
    found = next((v for v in variants if v.get("relationship_stage_id") == ending_id), None)
    return found.get("dialogue") if found else None


async def judge_conversation(db: AsyncSession, conversation: Conversation, project_id: str, scene_set: str | None) -> str | None:
    """결말 ID. 판정 대상이 아니거나 데이터가 없으면 None."""
    if scene_set != JUDGED_SCENE_SET or project_id not in ("fridge", "cloud"):
        return None
    tables = score_tables(project_id)
    if not tables:
        return None
    intents = await turn_intents(db, conversation, tables)
    if project_id == "fridge":
        return judge_fridge(intents, tables)[0]
    return judge_cloud(intents, tables)[0]
