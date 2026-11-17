"""냉장고·구름섬 10턴 스토리 개요 JSON 검증 (Python 표준 라이브러리만 사용).

프로젝트 루트에서 실행:
    python data/validate_story_outlines.py

검사 범위
1. 스키마: 필수 필드·자료형, 턴 1~10 순서·ID, phase 참조, 선택지→의도 참조, ID 중복
2. 원문 일치: 추출한 모든 문장(장면 정보, 첫 대사, 화자, 지문, 시스템 메시지, 선택지, 의도표, 고정 연출, 홍보 문구)이
   docs/stories/*/…-scenario.md 원문(마크다운 이스케이프만 해제)에 그대로 있는지, 표 행·(버튼) 수·턴 수가 원문과 같은지
3. 미확정 유지: 점수·관계 단계·성향 판정 값이 확정값으로 들어가지 않았는지
LLM 응답 품질, 프론트·백엔드·DB 연동은 검사하지 않는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTLINES = {
    # 시나리오 장면 카드 초안 추출본. 팀원의 공식 개요 fridge_story_outline.json과 별개 파일이다.
    "fridge": "data/fridge_data/scenario/fridge_scene_cards_draft.json",
    # 시나리오 장면 카드 초안 추출본. 팀원의 공식 개요 cloud_story_outline.json과 별개 파일이다.
    "cloud": "data/cloud_data/scenario/cloud_scene_cards_draft.json",
}
SCENARIOS = {p: f"docs/stories/{p}/{p}-scenario.md" for p in OUTLINES}
BIBLES = {p: f"docs/stories/{p}/{p}-story-bible.md" for p in OUTLINES}
CLOUD_NAMES = {"토토", "비비", "나나", "키키", "두두"}
LEVELS = {"bible_confirmed", "bible_draft", "scenario_draft", "unconfirmed"}
CONTENT_KEYS = {
    "title", "heading_phase_note", "goal", "situation", "advance_condition", "exceptions", "must_not_reveal_yet",
    "text", "label", "display_direction", "stage_direction", "stage_direction_after", "speaker",
    "intent_label", "button_example", "response_direction", "score_raw", "trigger_source_label", "source_label",
    "stage_raw",
}
NOT_FROM_SCENARIO = {"source_label"}  # 추출 위치 메타데이터(원문 라벨이 아닌 값 포함)


def unescape(text: str) -> str:
    return re.sub(r"\\([\[\]~!*_#|])", r"\1", text)


def turn_sections(md: str) -> dict[int, str]:
    out: dict[int, str] = {}
    current = None
    for line in md.splitlines():
        m = re.match(r"^### (\d+)턴 · ", line)
        if m:
            current = int(m.group(1)); out[current] = line + "\n"; continue
        if line.startswith("## ") or (line.startswith("### ") and current is not None):
            current = None
        if current is not None:
            out[current] += line + "\n"
    return out


def strings(value: Any, key: str | None = None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from strings(v, k)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item, key)
    elif isinstance(value, str) and key is not None:
        yield key, value


def run() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    personas = json.loads((ROOT / "data/cloud_data/persona/cloud_personas.json").read_text(encoding="utf-8"))
    persona_ids = {p["id"] for p in personas["personas"]}
    axes = json.loads((ROOT / "data/cloud_data/rules/cloud_trait_axes.json").read_text(encoding="utf-8"))

    for project, rel in OUTLINES.items():
        tag = f"[{project}]"
        try:
            data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            check(f"{tag} JSON 파싱", False, str(error)); continue
        check(f"{tag} JSON 파싱", True)
        raw_md = (ROOT / SCENARIOS[project]).read_text(encoding="utf-8")
        md = unescape(raw_md)
        bible = unescape((ROOT / BIBLES[project]).read_text(encoding="utf-8"))
        sections = {n: unescape(s) for n, s in turn_sections(raw_md).items()}

        required = {"schema_version": str, "project_id": str, "scope": str, "source_basis": list, "source_levels": dict,
                    "phases": list, "turn_slots": list, "turn_count": dict, "unconfirmed_items": dict}
        wrong = [k for k, t in required.items() if not isinstance(data.get(k), t)]
        check(f"{tag} 최상위 필수 필드·자료형", not wrong, ", ".join(wrong))
        if wrong:
            continue
        check(f"{tag} project_id", data["project_id"] == project)
        check(f"{tag} 출처 수준 4종 정의", set(data["source_levels"]) == LEVELS)
        check(f"{tag} 출처에 바이블·시나리오 포함", any(BIBLES[project] in s for s in data["source_basis"]) and any(SCENARIOS[project] in s for s in data["source_basis"]))
        check(f"{tag} 목표 10턴", data["turn_count"].get("target") == 10)
        check(f"{tag} 원문 턴 수 10", sorted(sections) == list(range(1, 11)), str(sorted(sections)))

        phases = data["phases"]
        phase_range = {p.get("id"): p.get("turn_range") for p in phases}
        turns = data["turn_slots"]
        check(f"{tag} 턴 슬롯 10개·순서·ID", [(t.get("turn_number"), t.get("turn_id")) for t in turns] == [(i, f"{project}_t{i:02d}") for i in range(1, 11)])
        check(f"{tag} phase 참조·턴 범위", all(t.get("phase_id") in phase_range and phase_range[t["phase_id"]][0] <= t["turn_number"] <= phase_range[t["phase_id"]][1] for t in turns))
        check(f"{tag} phase 범위가 1~10을 빈틈없이 덮음", sorted(n for r in phase_range.values() for n in range(r[0], r[1] + 1)) == list(range(1, 11)))

        slot_keys = {"turn_id": str, "turn_number": int, "phase_id": str, "source": dict, "scene": dict, "speakers": list,
                     "opening_lines": list, "follow_up_lines": list, "system_messages": list, "intents": list,
                     "promotion_hooks": list, "status": str}
        bad_slots = [t.get("turn_id") for t in turns if any(not isinstance(t.get(k), typ) for k, typ in slot_keys.items())]
        check(f"{tag} 턴 슬롯 필수 필드·자료형", not bad_slots, ", ".join(map(str, bad_slots)))
        if bad_slots:
            continue
        check(f"{tag} 모든 턴은 시나리오 초안 출처·상태", all(t["source"].get("source_level") == "scenario_draft" and t["source"].get("document") == SCENARIOS[project] and "초안" in t["status"] for t in turns))

        missing: list[str] = []
        count_mismatch: list[str] = []
        for t in turns:
            n = t["turn_number"]
            section = sections.get(n, "")
            heading = section.splitlines()[0] if section else ""
            if t["source"].get("heading") != heading:
                count_mismatch.append(f"t{n} heading")
            if f"· {t['scene'].get('title')} (" not in heading:
                count_mismatch.append(f"t{n} title")
            for key, value in strings({k: v for k, v in t.items() if k not in ("source", "status", "choice_score_changes", "free_input_response_guidelines")}):
                if key in CONTENT_KEYS and key not in NOT_FROM_SCENARIO and value not in section:
                    missing.append(f"t{n}.{key}: {value[:40]}")
            for value in [x for it in t["intents"] for x in it.get("free_input_examples", [])]:
                if f'"{value}"' not in section:
                    missing.append(f"t{n}.free_input_examples: {value[:40]}")
            table_rows = [l for l in section.splitlines() if l.startswith("|")]
            intent_rows = max(0, len(table_rows) - 2) if t["intents"] else 0
            if t.get("final_lines_by_stage"):
                intent_rows = 0
            if len(t["intents"]) != intent_rows:
                count_mismatch.append(f"t{n} 의도표 행 {len(t['intents'])}≠{intent_rows}")
            buttons = section.count("(버튼)")  # "(버튼 없음)"은 포함되지 않음
            if len(t.get("fixed_choices") or []) != buttons:
                count_mismatch.append(f"t{n} 버튼 {len(t.get('fixed_choices') or [])}≠{buttons}")
            if t["system_messages"] and not all("[시스템" in section for _ in t["system_messages"]):
                count_mismatch.append(f"t{n} 시스템 메시지")
            if section.count("[시스템") != len(t["system_messages"]) + sum(1 for x in (t.get("fixed_sequence") or []) if x.get("kind") == "system"):
                count_mismatch.append(f"t{n} 시스템 표기 수")
            for line in t["opening_lines"] + t["follow_up_lines"] + (t.get("fixed_sequence") or []):
                if "also_in_bible" in line and line["also_in_bible"] != (line.get("text", "") in bible):
                    count_mismatch.append(f"t{n} also_in_bible")
            for row in t.get("final_lines_by_stage") or []:
                if row.get("also_in_bible") != (row.get("text") in bible):
                    count_mismatch.append(f"t{n} 단계 대사 also_in_bible")
        check(f"{tag} 추출 문장이 모두 시나리오 원문에 존재", not missing, "; ".join(missing[:8]))
        check(f"{tag} 제목·표 행·(버튼)·시스템 표기 수가 원문과 일치", not count_mismatch, "; ".join(count_mismatch[:8]))

        intent_ids = [it.get("intent_id") for t in turns for it in t["intents"]]
        check(f"{tag} 의도 ID 중복 없음", len(intent_ids) == len(set(intent_ids)))
        choice_refs_ok = all(c.get("intent_id") in {it["intent_id"] for it in t["intents"]} and c.get("label") == next(it["button_example"] for it in t["intents"] if it["intent_id"] == c["intent_id"]) for t in turns for c in (t.get("fixed_choices") or []))
        check(f"{tag} 선택지→의도 참조·문장 일치", choice_refs_ok)
        scores = [t["choice_score_changes"] for t in turns if t.get("choice_score_changes")]
        check(f"{tag} 점수는 시나리오 제안값·미확정 표기", all("미확정" in s.get("status", "") for s in scores))
        check(f"{tag} 점수 원문값과 의도표 일치", all({v["intent_id"]: v["raw"] for v in s["values"]} == {it["intent_id"]: it["score_raw"] for it in t["intents"] if it.get("score_raw")} for t in turns for s in [t.get("choice_score_changes")] if s))
        check(f"{tag} 마지막 턴은 입력 없음 표기", "입력 없음" in sections[10] and any(n.get("label") == "입력 없음" for n in turns[9]["scene"].get("extra_notes", [])))

        uc = data["unconfirmed_items"]
        bible_raw = (ROOT / BIBLES[project]).read_text(encoding="utf-8")
        bible_todo = [unescape(re.sub(r"^\s*- \[ \] ", "", l)) for l in bible_raw.split("미정 사항", 1)[1].splitlines() if l.strip().startswith("- [ ]")]
        md_todo = [unescape(re.sub(r"^- \[ \] ", "", l)) for l in raw_md.split("### 팀에서 정해야 할 것", 1)[1].splitlines() if l.startswith("- [ ]")]
        values = list(uc.values())
        check(f"{tag} 미정 사항 목록이 바이블·시나리오 체크리스트와 일치", len(values) == 2 and values[0] == bible_todo and values[1] == md_todo, f"바이블 {len(bible_todo)}개, 시나리오 {len(md_todo)}개")

        if project == "fridge":
            check(f"{tag} 화자 표기는 원문 '회장'", all(t["speakers"] in ([], ["회장"]) for t in turns))
            check(f"{tag} phase 비트는 바이블 6장 원문", all(p.get("bible_beat") in bible and p.get("source_level") == "bible_draft" for p in phases))
            rel = data.get("relationship_and_scoring", {})
            check(f"{tag} 관계 단계 기준 미확정 유지", rel.get("thresholds") is None and "미확정" in rel.get("status", "") and "미확정" in rel.get("thresholds_status", ""))
            check(f"{tag} 10턴 단계별 대사 3종(바이블 가안 동일)", [r.get("stage_raw") for r in turns[9].get("final_lines_by_stage", [])] == ["1", "2", "3"] and all(r.get("also_in_bible") for r in turns[9]["final_lines_by_stage"]))
            check(f"{tag} 4턴 두 번째 대사·9턴 딩동 보존", len(turns[3]["follow_up_lines"]) == 1 and any(m.get("label") == "시스템: 딩동" for m in turns[8]["system_messages"]))
        else:
            check(f"{tag} 화자는 다섯 대원만", all(set(t["speakers"]) <= CLOUD_NAMES for t in turns))
            check(f"{tag} 의도의 대원 ID가 페르소나 파일에 존재", all(it.get("trait_persona_id") in persona_ids for t in turns for it in t["intents"] if it.get("trait_label")))
            check(f"{tag} 1턴은 채점 없음(닉네임 턴)", turns[0].get("choice_score_changes") is None and not turns[0].get("fixed_choices"))
            check(f"{tag} 10턴 고정 연출(두두→시스템→키키→비비→끊김)", [x.get("speaker") or x.get("kind") for x in turns[9].get("fixed_sequence") or []] == ["두두", "system", "키키", "비비", "cut"])
            check(f"{tag} 성향 판정 규칙 미확정 유지(cloud_trait_axes.json)", axes["choice_scores"].get("per_turn_values") is None and axes.get("central_balance_threshold") is None and axes.get("axis_zero_and_tie_policy") is None and all(v is None for k, v in axes["initial_total_values"].items() if k != "status"))
            check(f"{tag} 시나리오 판정 규칙은 초안·미확정 표기", "미확정" in data.get("scenario_draft_scoring", {}).get("status", ""))
            check(f"{tag} 기존 결과 카드 참조 유지", data.get("post_cliffhanger", {}).get("result_card_ref") == "data/ending/cloud_result_types.json")

    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    passed = sum(ok for _, ok, _ in checks)
    print(f"\n스토리 개요 검증: {passed}/{len(checks)} 통과")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(run())
