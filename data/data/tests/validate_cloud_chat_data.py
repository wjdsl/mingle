"""구름섬 채팅 데이터 정적 검증 (Python 표준 라이브러리만 사용).

프로젝트 루트에서 실행:
    python data/tests/validate_cloud_chat_data.py

이 검사는 JSON 문법/필드/파일 간 참조와 일부 기획서 핵심 값만 검사합니다.
LLM의 실제 응답 품질이나 프론트·백엔드·DB 연동은 검사하지 않습니다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "personas": "data/persona/cloud_personas.json",
    "world": "data/rag/cloud_world_knowledge.json",
    "chat": "data/rules/cloud_chat_rules.json",
    "axes": "data/rules/cloud_trait_axes.json",
    "scenario": "data/scenario/cloud_story_outline.json",
    "results": "data/ending/cloud_result_types.json",
    "state": "data/state/cloud_state_schema.json",
    "tests": "data/tests/cloud_chat_test_cases.json",
}
REQUIRED = {
    "personas": {"schema_version": str, "project_id": str, "personas": list},
    "world": {"schema_version": str, "project_id": str, "allowed_facts": list, "excluded_answer_topics": list},
    "chat": {"schema_version": str, "project_id": str, "per_turn": dict, "input": dict, "user_role": dict,
             "content_safety": dict, "promotion": dict, "error_fallback": dict},
    "axes": {"schema_version": str, "project_id": str, "axes": list, "result_quadrants": list,
             "per_free_input_score_bound": dict, "choice_scores": dict},
    "scenario": {"schema_version": str, "project_id": str, "phases": list, "turn_slots": list,
                 "turn_count": dict, "post_cliffhanger": dict},
    "results": {"schema_version": str, "project_id": str, "result_cards": list},
    "state": {"schema_version": str, "project_id": str, "fields": list, "storage_policy": dict},
    "tests": {"schema_version": str, "project_id": str, "cases": list},
}
EXPECTED_CHARACTERS = {
    "토토": "cloud_toto", "비비": "cloud_bibi", "나나": "cloud_nana",
    "키키": "cloud_kiki", "두두": "cloud_dudu",
}
EXPECTED_RESULT_TYPES = {v: f"cloud_result_{v.removeprefix('cloud_')}" for v in EXPECTED_CHARACTERS.values()}
EXPECTED_MAP = {
    ("positive", "positive"): "cloud_result_toto",
    ("positive", "negative"): "cloud_result_bibi",
    ("negative", "negative"): "cloud_result_nana",
    ("negative", "positive"): "cloud_result_kiki",
    ("center", "center"): "cloud_result_dudu",
}
EXPECTED_PHASES = [("cloud_phase_join", 1, 2), ("cloud_phase_depart", 3, 4),
                   ("cloud_phase_crisis", 5, 6), ("cloud_phase_rescue", 7, 9),
                   ("cloud_phase_teaser", 10, 10)]


def get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Return None for a missing/nested-wrong-type key instead of raising an exception."""
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return obj


def records(value: Any) -> list[dict[str, Any]]:
    """Return a safe list for checks, with type validity checked separately."""
    return value if isinstance(value, list) and all(isinstance(x, dict) for x in value) else []


def unique(items: list[Any]) -> bool:
    return len(items) == len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items})


def report(checks: list[tuple[str, bool, str]]) -> int:
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    passed = sum(item[1] for item in checks)
    print(f"\nJSON 정적 검증: {passed}/{len(checks)} 통과")
    print("참고: 채팅 행동 테스트 20건, AI/프론트/백엔드/DB 연동 테스트는 실행하지 않았습니다.")
    return 0 if passed == len(checks) else 1


def run() -> int:
    checks: list[tuple[str, bool, str]] = []
    data: dict[str, dict[str, Any]] = {}

    def check(name: str, ok: Any, detail: str = "") -> None:
        checks.append((name, ok is True or (isinstance(ok, bool) and ok), detail))

    for name, relative in FILES.items():
        filepath = PROJECT_ROOT / relative
        try:
            value = json.loads(filepath.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("루트는 JSON 객체여야 합니다")
            data[name] = value
            check(f"{name}: JSON 파싱", True)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            check(f"{name}: JSON 파싱", False, f"{relative}: {error}")

    if len(data) != len(FILES):
        return report(checks)

    for name, fields in REQUIRED.items():
        obj = data[name]
        wrong = [field for field, typ in fields.items() if type(obj.get(field)) is not typ]
        check(f"{name}: 필수 필드·자료형", not wrong, f"오류: {', '.join(wrong)}" if wrong else "")

    if any(not ok for _, ok, _ in checks):
        return report(checks)  # malformed input must fail cleanly, never traceback

    p = data["personas"]
    w = data["world"]
    c = data["chat"]
    a = data["axes"]
    s = data["scenario"]
    r = data["results"]
    st = data["state"]
    t = data["tests"]

    check("모든 파일의 프로젝트 ID가 cloud", all(x.get("project_id") == "cloud" for x in data.values()))
    check("모든 JSON 규격 버전 0.2", all(x.get("schema_version") == "0.2" for x in data.values()))
    check("모든 파일의 출처 목록 존재", all(isinstance(x.get("source_basis"), list) and x["source_basis"] for x in data.values()))

    personas = records(p["personas"])
    check("캐릭터 항목이 객체 목록", len(personas) == len(p["personas"]))
    check("캐릭터 수 5", len(personas) == 5)
    check("캐릭터 이름·ID 정본 일치", {(x.get("name"), x.get("id")) for x in personas} == set(EXPECTED_CHARACTERS.items()))
    check("캐릭터 ID 중복 없음", unique([x.get("id") for x in personas]))
    check("페르소나 주요 필드와 금지 규칙", all(
        isinstance(x.get("core"), str) and x["core"] and
        isinstance(x.get("forbidden"), list) and x["forbidden"] and
        isinstance(get(x, "speech", "style"), str) and
        isinstance(get(x, "speech", "user_address"), list) and get(x, "speech", "user_address")
        for x in personas))
    check("다섯 대원 모두 반말", all(get(x, "speech", "register") == "반말" for x in personas))
    check("토토 두려움 노출은 1회", next((x.get("hidden_side_exposure_limit_per_experience") for x in personas if x.get("id") == "cloud_toto"), None) == 1)
    dudu = next((x for x in personas if x.get("id") == "cloud_dudu"), {})
    check("두두 사용자 호칭은 닉네임 변수", get(dudu, "speech", "user_address") == ["{nickname}"])
    check("두두 닉네임 첫 호명은 마지막 장면", get(dudu, "speech", "nickname_first_mention_phase_id") == "cloud_phase_teaser")

    facts = records(w["allowed_facts"])
    check("공개 세계관 5개", len(facts) == len(w["allowed_facts"]) == 5)
    check("세계관 항목 ID 중복 없음", unique([x.get("id") for x in facts]))
    check("세계관 주제 정본 일치", {x.get("topic") for x in facts} == {"구름섬", "에너지 구름", "섬 추락 사건", "구조대", "위험한 구름 지대"})
    check("비공개 정보 4개", len(w["excluded_answer_topics"]) == 4 and len(set(w["excluded_answer_topics"])) == 4)
    check("비공개 정보는 추측도 금지", "추측" in str(w.get("unknown_answer_policy", "")))

    check("한 턴 최대 3명 발화", get(c, "per_turn", "max_speakers") == 3)
    check("캐릭터별 한 턴 지문 최대 1개", get(c, "per_turn", "max_stage_direction_per_speaker") == 1)
    check("두두 호명 단계 참조 일치", get(c, "per_turn", "dudu_nickname_first_mention_phase_id") == "cloud_phase_teaser")
    check("자유 입력 최대 300자", get(c, "input", "max_length_characters") == 300)
    check("고정 선택지와 자유 입력 모두 사용", get(c, "input", "supports_fixed_choice") is True and get(c, "input", "supports_free_text") is True)
    check("입력 분류 미확정 값은 ID로 만들지 않음", get(c, "input", "fixed_choice_to_free_text_id_inference") is False)
    check("기본 호칭은 신입 대원", get(c, "user_role", "nickname_fallback") == "신입 대원")
    check("실명 수집 금지", get(c, "user_role", "real_name_collection") is False)
    check("사전 지정된 본편 URL 없음", get(c, "promotion", "main_work_url") is None and r.get("original_work_link") is None)
    check("위기 응답이 스토리 진행보다 우선", "안전" in str(get(c, "content_safety", "safety_override")))
    check("욕설·혐오·연애·선정적 요구 처리 규칙", bool(get(c, "content_safety", "abusive_or_hate_content_handling")) and bool(get(c, "content_safety", "romantic_or_sexual_request_handling")))
    check("AI 응답 실패 대체안은 미확정 표기", get(c, "error_fallback", "fallback_response_text") is None and get(c, "error_fallback", "response_implementation") == "미확정")
    check("닫은 홍보 콘텐츠 재노출 금지", get(c, "promotion", "closed_content_same_run_resurfacing") is False)

    phases = records(s["phases"])
    turns = records(s["turn_slots"])
    check("단계 목록 객체 형식", len(phases) == len(s["phases"]))
    check("단계 5개 및 턴 범위 일치", [
        (x.get("id"), *(x.get("turn_range") if isinstance(x.get("turn_range"), list) and len(x["turn_range"]) == 2 else (None, None)))
        for x in phases] == EXPECTED_PHASES)
    check("약 10턴", get(s, "turn_count", "approximate") is True and get(s, "turn_count", "target") == 10)
    check("턴 슬롯 10개", len(turns) == len(s["turn_slots"]) == 10)
    check("턴 1부터 10까지 순서·ID 일치", [(x.get("turn_number"), x.get("turn_id")) for x in turns] == [(i, f"cloud_t{i:02d}") for i in range(1, 11)])
    phase_by_turn = {turn: phase_id for phase_id, start, stop in EXPECTED_PHASES for turn in range(start, stop + 1)}
    check("턴의 phase_id 참조 일치", all(phase_by_turn.get(x.get("turn_number")) == x.get("phase_id") for x in turns))
    check("확정 전 턴별 장면·선택지·점수 없음", all(all(x.get(k, "MISSING") is None for k in ("scene", "speakers", "fixed_choices", "choice_score_changes", "free_input_response_guidelines")) for x in turns))
    check("마지막 장면 후 결과카드 참조", get(s, "post_cliffhanger", "result_card_ref") == FILES["results"])

    axes = records(a["axes"])
    mappings = records(a["result_quadrants"])
    check("성향 축 2개", [x.get("id") for x in axes] == ["relationship_goal", "stability_challenge"])
    check("성향 축 방향 정본 일치", len(axes) == 2 and axes[0].get("negative_label") == "관계·공감" and axes[0].get("positive_label") == "목표·효율" and axes[1].get("negative_label") == "안정·안전" and axes[1].get("positive_label") == "도전·변화")
    check("자유 입력 축별 점수 -2~+2", get(a, "per_free_input_score_bound", "min") == -2 and get(a, "per_free_input_score_bound", "max") == 2 and get(a, "per_free_input_score_bound", "applies_per_axis") is True)
    check("고정 선택지 점수 미확정", get(a, "choice_scores", "per_turn_values") is None)
    initial_totals = a.get("initial_total_values")
    check("초깃값·두두 중앙 범위·경계 미확정", isinstance(initial_totals, dict) and initial_totals.get("relationship_goal") is None and initial_totals.get("stability_challenge") is None and a.get("central_balance_threshold") is None and a.get("axis_zero_and_tie_policy") is None)
    check("성향 결과 매핑 5개·좌표 중복 없음", len(mappings) == len(a["result_quadrants"]) == 5 and unique([(x.get("x"), x.get("y")) for x in mappings]))
    check("성향 좌표와 캐릭터 5종 매핑 일치", {(x.get("x"), x.get("y")): x.get("result_type_id") for x in mappings} == EXPECTED_MAP)

    cards = records(r["result_cards"])
    check("결과 카드 항목이 객체 목록", len(cards) == len(r["result_cards"]))
    check("결과 카드 수 5", len(cards) == 5)
    check("결과 타입 ID 중복 없음", unique([x.get("result_type_id") for x in cards]))
    check("페르소나와 결과 카드 1:1 연결", {(x.get("id"), x.get("result_type_id")) for x in personas} == set(EXPECTED_RESULT_TYPES.items()) and {(x.get("character_id"), x.get("result_type_id")) for x in cards} == set(EXPECTED_RESULT_TYPES.items()))
    check("결과 타입 표시 이름·캐릭터 일치", {(x.get("character_name"), x.get("character_id")) for x in cards} == set(EXPECTED_CHARACTERS.items()))
    check("결과 문구는 가안으로 표시", "가안" in str(r.get("result_card_text_status", "")) and all(x.get("description") for x in cards))
    check("결과 매핑 파일 참조 일치", r.get("mapping_rule_file") == FILES["axes"])
    check("확정되지 않은 이미지 경로를 임의 설정하지 않음", all(x.get("image_path", "INVALID") is None for x in cards))

    fields = records(st["fields"])
    check("진행 상태 필드는 객체 목록", len(fields) == len(st["fields"]))
    check("진행 상태 필드 중복 없음", unique([x.get("name") for x in fields]))
    field_names = {x.get("name") for x in fields}
    check("성향·현재 턴·결과 필드 존재", {"project_id", "current_turn", "phase_id", "relationship_goal_total", "stability_challenge_total", "result_type_id"}.issubset(field_names))
    check("다시 시작해도 남는 결과 도감 필드 제안", "obtained_result_type_ids" in field_names)
    check("사용자 데이터 로컬 저장 원칙", "브라우저" in str(get(st, "storage_policy", "primary")))
    check("상태 설계는 실제 구현 아닌 제안", "제안" in str(st.get("status", "")))

    cases = records(t["cases"])
    check("행동 테스트 객체 목록", len(cases) == len(t["cases"]))
    check("행동 테스트 수 20", len(cases) == 20)
    check("행동 테스트 ID 01~20 및 중복 없음", {x.get("id") for x in cases} == {f"CHAT-{i:02d}" for i in range(1, 21)} and unique([x.get("id") for x in cases]))
    check("행동 테스트가 미실행으로 표시", all(x.get("status") == "검증 미실행" for x in cases))

    return report(checks)


if __name__ == "__main__":
    raise SystemExit(run())
