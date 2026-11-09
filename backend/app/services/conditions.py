"""조건 평가기.

스토리 이벤트 / 엔딩 / 마케팅 Trigger가 공통으로 사용하는 선언적 조건 DSL.

예시:
    {"all": [{"turn_gte": 3}, {"affinity_gte": 40}]}
    {"stage_in": ["친밀", "각별"]}
    {"keyword_any": ["선물", "굿즈"]}
    {"flag": "달빛 정원"}

지원 키:
    turn_gte / min_turns, turn_lte / max_turns
    affinity_gte / min_affinity, affinity_lte / max_affinity
    trust_gte, stage_in, stage_not_in, chapter_gte, chapter_in
    keyword_any, keyword_all, keyword_none
    flag, not_flag, flags_all, flags_none
    note_category_in
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ConditionContext:
    turn_count: int = 0
    affinity: int = 0
    trust: int = 0
    stage: str = ""
    chapter: int = 1
    flags: dict = field(default_factory=dict)
    text: str = ""
    note_keys: set[str] = field(default_factory=set)
    note_categories: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.text = (self.text or "").lower()
        self.flags = self.flags or {}


def evaluate(conditions: dict | list | None, ctx: ConditionContext) -> bool:
    if not conditions:
        return False
    if isinstance(conditions, list):
        return all(evaluate(item, ctx) for item in conditions)
    if not isinstance(conditions, dict):
        return False

    if "all" in conditions and not all(evaluate(item, ctx) for item in conditions["all"]):
        return False
    if "any" in conditions and not any(evaluate(item, ctx) for item in conditions["any"]):
        return False
    if "none" in conditions and any(evaluate(item, ctx) for item in conditions["none"]):
        return False

    for key, value in conditions.items():
        if key in ("all", "any", "none"):
            continue
        if not _check(key, value, ctx):
            return False
    return True


def _check(key: str, value, ctx: ConditionContext) -> bool:  # noqa: C901
    if key in ("turn_gte", "min_turns"):
        return ctx.turn_count >= int(value)
    if key in ("turn_lte", "max_turns"):
        return ctx.turn_count <= int(value)
    if key in ("affinity_gte", "min_affinity"):
        return ctx.affinity >= int(value)
    if key in ("affinity_lte", "max_affinity"):
        return ctx.affinity <= int(value)
    if key == "trust_gte":
        return ctx.trust >= int(value)
    if key == "stage_in":
        return ctx.stage in set(value)
    if key == "stage_not_in":
        return ctx.stage not in set(value)
    if key == "chapter_gte":
        return ctx.chapter >= int(value)
    if key == "chapter_in":
        return ctx.chapter in set(value)
    if key == "keyword_any":
        return any(str(word).lower() in ctx.text for word in value)
    if key == "keyword_all":
        return all(str(word).lower() in ctx.text for word in value)
    if key == "keyword_none":
        return all(str(word).lower() not in ctx.text for word in value)
    if key == "flag":
        return bool(ctx.flags.get(str(value)))
    if key == "not_flag":
        return not bool(ctx.flags.get(str(value)))
    if key == "flags_all":
        return all(bool(ctx.flags.get(str(item))) for item in value)
    if key == "flags_none":
        return all(not bool(ctx.flags.get(str(item))) for item in value)
    if key == "note_category_in":
        return bool(ctx.note_categories & set(value))
    # 알 수 없는 조건은 안전하게 불충족 처리
    return False
