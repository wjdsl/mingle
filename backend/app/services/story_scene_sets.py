"""scenario_draft_v1 장면 세트: 시나리오 장면 카드 초안 JSON(10턴) → Scene 객체.

- 장면 문장(첫 대사·사건·버튼·반응 방향·예외·먼저 말하면 안 되는 것)은 초안 JSON의 원문만 쓴다.
- 점수(score_raw, choice_score_changes)는 읽지 않는다. 관계 단계·성향 판정이 미확정이기 때문이다.
- 냉장고 10턴 마무리 대사는 공식 fridge_trailer_cuts.json의 1단계 대사를 쓴다(관계 단계 계산 미구현이라 1단계 고정).
- 화자 이름은 공식 페르소나 display_name을 쓴다(초안 표기 '회장' → '냉장고 회장').
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.services.story_data import load_draft, load_official
from app.services.story_scenes import (
    PROJECTS,
    Scene,
    SceneChoice,
    SceneIntent,
    SceneLine,
    StoryProjectDef,
)

SCENARIO_SET = "scenario_draft_v1"
MOCK_FREE_REPLY = "[Mock] 자유 입력에 대한 고정 응답입니다. AI가 연결되지 않았습니다."
_HANDLED_NOTES = {"입력 없음", "대사 앞 지문"}


def scenario_persona_slug(base_slug: str) -> str:
    return f"{base_slug}-scenario-v1"


def _first_quote(text: str) -> str:
    match = re.search(r'"([^"]+)"', text or "")
    return match.group(1) if match else ""


def _line(item: dict[str, Any], speaker_map: dict[str, str]) -> SceneLine | None:
    if item.get("kind") == "system":
        label, text = item.get("label", "시스템"), item.get("text")
        return SceneLine("시스템", f"[{label}] {text}" if text else f"[{label}]")
    if item.get("kind") != "line":
        return None
    speaker = speaker_map.get(item.get("speaker", ""), item.get("speaker", ""))
    direction = item.get("display_direction") or item.get("stage_direction") or item.get("stage_direction_after")
    return SceneLine(speaker, item.get("text") or "", direction)


def format_line(line: SceneLine, project_id: str) -> str:
    """화면/프롬프트용 한 줄 표기. 냉장고는 [디스플레이: …] 줄, 구름섬은 (지문)."""
    if line.speaker == "시스템":
        return line.text
    if project_id == "fridge":
        prefix = f"[디스플레이: {line.direction}]\n" if line.direction else ""
        return f"{prefix}{line.text}".strip()
    direction = f"({line.direction}) " if line.direction else ""
    return f"{direction}{line.text}".strip()


def _scene_from_slot(project_id: str, slot: dict[str, Any], speaker_map: dict[str, str], trailer_line: SceneLine | None) -> Scene:
    card = slot["scene"]
    notes = {n["label"]: n["text"] for n in card.get("extra_notes", [])}
    opening = tuple(l for l in (_line(x, speaker_map) for x in slot.get("opening_lines", [])) if l)
    follow = tuple(l for l in (_line(x, speaker_map) for x in slot.get("follow_up_lines", [])) if l)
    systems = tuple(
        f"[{m['label']}] {m['text']}" if m.get("text") else f"[{m['label']}]"
        for m in slot.get("system_messages", [])
    )
    intents = tuple(
        SceneIntent(
            id=it["intent_id"],
            label=it["intent_label"],
            response_direction=it.get("response_direction") or "",
            has_button=bool(it.get("button_example")),
        )
        for it in slot.get("intents", [])
    )
    by_id = {it["intent_id"]: it for it in slot.get("intents", [])}
    choices = tuple(
        SceneChoice(
            id=c["choice_id"],
            label=c["label"],
            reference_reply=_first_quote(by_id[c["intent_id"]].get("response_direction", "")) or MOCK_FREE_REPLY,
            reaction="",
            direction=by_id[c["intent_id"]].get("response_direction", ""),
        )
        for c in (slot.get("fixed_choices") or [])
    )
    input_mode = "none" if "입력 없음" in notes else "input"
    fixed: tuple[SceneLine, ...] = ()
    if input_mode == "none":
        if slot.get("fixed_sequence"):
            fixed = tuple(l for l in (_line(x, speaker_map) for x in slot["fixed_sequence"]) if l and l.text)
        elif trailer_line is not None:
            display = re.search(r"\[디스플레이: ([^\]]+)\]", notes.get("대사 앞 지문", ""))
            fixed = (SceneLine(trailer_line.speaker, trailer_line.text, display.group(1) if display else None),)
    closing: tuple[SceneLine, ...] = ()
    narration = re.search(r'공통 지문 "([^"]+)"', card.get("advance_condition", ""))
    if narration:
        closing = (SceneLine("내레이션", narration.group(1)),)
    first = opening[0] if opening else (fixed[0] if fixed else SceneLine(speaker_map.get("", ""), ""))
    return Scene(
        title=card["title"],
        situation=card.get("situation", ""),
        opening_speaker=first.speaker,
        opening="\n".join(f"{l.speaker}: {format_line(l, project_id)}" for l in opening),
        goal=card.get("goal", ""),
        choices=choices,
        default_reply=MOCK_FREE_REPLY,
        event=" / ".join(systems) or None,
        avoid=tuple(x for x in [card.get("must_not_reveal_yet", "")] if x),
        opening_lines=opening,
        system_messages=systems,
        follow_up_lines=follow,
        closing_lines=closing,
        input_mode=input_mode,
        fixed_lines=fixed,
        advance_condition=card.get("advance_condition", ""),
        exceptions=card.get("exceptions", ""),
        notes=tuple(f"{k}: {v}" for k, v in notes.items() if k not in _HANDLED_NOTES),
        intents=intents,
        source_level="scenario_draft",
    )


@lru_cache(maxsize=4)
def scenario_project(project_id: str) -> StoryProjectDef | None:
    base = PROJECTS.get(project_id)
    official = load_official(project_id)
    draft = load_draft(project_id)
    if base is None or official is None or draft is None:
        return None
    if project_id == "fridge":
        name = official.get("persona")["display_name"]
        speaker_map = {"회장": name, "": name}
        stage1 = next((v for v in official.get("trailer")["relationship_variants"] if v.get("relationship_stage_id") == "fridge_rel_stage_1"), None)
        trailer_line = SceneLine(name, stage1["dialogue"]) if stage1 else None
        speakers, max_lines = (name,), 1
        fallback = official.get("persona")["speech"].get("default_user_address", base.nickname_fallback)
    else:
        names = tuple(p["name"] for p in official.get("personas")["personas"])
        speaker_map = {n: n for n in names}
        trailer_line = None
        speakers, max_lines = names, int(official.get("chat_rules")["per_turn"].get("max_speakers", 3))
        fallback = official.get("chat_rules")["user_role"].get("nickname_fallback", base.nickname_fallback)
    scenes = tuple(_scene_from_slot(project_id, slot, speaker_map, trailer_line) for slot in draft["turn_slots"])
    return StoryProjectDef(
        id=project_id,
        title=base.title,
        persona_slug=scenario_persona_slug(base.persona_slug),
        persona_name=f"{base.persona_name} (시나리오 초안)",
        speakers=speakers,
        max_lines=max_lines,
        nickname_fallback=fallback,
        scenes=scenes,
        system_rules=base.system_rules,
        guardrail_reply=base.guardrail_reply,
        scene_set=SCENARIO_SET,
    )


def clear_cache() -> None:
    scenario_project.cache_clear()
