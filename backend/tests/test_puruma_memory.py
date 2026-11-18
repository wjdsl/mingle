"""푸르마 전용 User Note 정책 테스트 (DB·외부 API 없음).

팀 데이터: data/tests/pruma_usernote_importance_tests.json (저장 대상 30건 + 제외 4건).
구간별 선택(4건)은 이번 단계에서 추출하지 않으므로 측정 대상 26건과 분리한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import memory
from app.services.memory import (
    IMPORTANCE_RANK,
    PURUMA_EXTRACTED_FIELDS,
    PURUMA_FIELDS,
    PURUMA_MAX_NOTES,
    PurumaNote,
    extract_puruma_notes,
    memory_skip_reason,
    merge_puruma_notes,
    puruma_notes_for_prompt,
    update_puruma_notes,
)

DATA = json.loads((Path(__file__).resolve().parents[2] / "data/tests/pruma_usernote_importance_tests.json").read_text(encoding="utf-8"))
FIELD = {"호칭/별명": "nickname", "관심사": "interest", "약속/응원": "promise", "반복 주제": "repeated_topic", "구간별 선택": "section_choice"}
IN_SCOPE = [case for case in DATA["cases"] if FIELD[case["field"]] != "section_choice"]


def _best(notes: list[PurumaNote], field: str) -> PurumaNote | None:
    hits = [note for note in notes if note.field == field]
    return max(hits, key=lambda note: IMPORTANCE_RANK[note.importance]) if hits else None


# --- 팀 데이터 30건 ---

def test_team_cases_extraction_and_importance_rate():
    extracted = correct = 0
    for case in IN_SCOPE:
        note = _best(extract_puruma_notes(case["input"], 1), FIELD[case["field"]])
        extracted += note is not None
        correct += note is not None and note.importance == case["expected"]
    assert len(IN_SCOPE) == 26
    # 측정 결과(2026-11-18): 추출 26/26, 중요도 26/26. 규칙을 이 데이터를 보며 만들었으므로 하한만 고정한다.
    assert extracted >= 24 and correct >= 22


@pytest.mark.parametrize("case", DATA["excluded_examples"], ids=lambda case: case["id"])
def test_team_excluded_examples_are_never_stored(case):
    assert extract_puruma_notes(case["input"], 1) == []


def test_section_choice_is_defined_but_not_extracted():
    assert "section_choice" in PURUMA_FIELDS and "section_choice" not in PURUMA_EXTRACTED_FIELDS
    for case in DATA["cases"]:
        if FIELD[case["field"]] == "section_choice":
            assert all(note.field != "section_choice" for note in extract_puruma_notes(case["input"], 1))


# --- 위기·개인정보·민감정보 ---

@pytest.mark.parametrize("text", [
    "죽고 싶어. 근데 음악은 좋아해",
    "요즘 자해 생각이 나. 앞으로 나를 콩이라고 불러줘",
    "자살하고 싶다는 생각만 들어",
    "살기 싫어 그래도 응원할게",
])
def test_crisis_input_stores_nothing_and_skips_recall(text):
    assert memory_skip_reason(text) == "crisis"
    assert extract_puruma_notes(text, 3) == []
    existing = [PurumaNote("interest:음악", "interest", "음악", "medium", 1, 1)]
    assert update_puruma_notes(existing, text, 3) == existing  # 새 기억 0건
    assert puruma_notes_for_prompt(existing, text) == []  # 위기 턴에는 회상하지 않음


@pytest.mark.parametrize("text", [
    "내 이름은 김민수야. 영화 좋아해",
    "제 이름은 이지은이에요",
    "내 학번은 20231234야 꼭 기억해",
    "내 생일은 3월 5일이야",
    "010-1234-5678로 연락해",
    "메일은 a.b@test.com 이야",
    "우리 집 주소는 대구야",
    "요즘 우울해서 병원 다녀. 그림 좋아해",
    "교회 다니는 걸 좋아해",
    "정치 얘기 좋아해",
    "친구 지영이가 영화 좋아해",
    "민수 씨가 음악 좋아한대",
])
def test_personal_or_sensitive_or_other_person_input_is_not_stored(text):
    assert memory_skip_reason(text) == "sensitive"
    assert extract_puruma_notes(text, 1) == []


@pytest.mark.parametrize("text", ["나 너 좋아해", "그거 좋아", "오늘 날씨 좋다", "몰라", "ㅋㅋ"])
def test_non_personalizable_input_is_not_stored(text):
    assert extract_puruma_notes(text, 1) == []


# --- 정규화·중복·상한 ---

def test_same_interest_is_merged_and_upgraded_to_high_on_repeat():
    first = update_puruma_notes([], "난 음악 좋아해", 1)
    assert [(n.key, n.importance) for n in first] == [("interest:음악", "medium")]
    second = update_puruma_notes(first, "나는 음악을 좋아해", 2)
    assert len(second) == 1
    assert second[0].importance == "high" and second[0].created_at_turn == 1 and second[0].updated_at_turn == 2


def test_nickname_has_single_slot_and_latest_wins():
    notes = update_puruma_notes([], "앞으로 나를 선배곰이라고 불러줘", 1)
    notes = update_puruma_notes(notes, "내 별명은 콩이야. 그렇게 불러도 돼", 2)
    nicknames = [n for n in notes if n.field == "nickname"]
    assert [(n.value, n.importance) for n in nicknames] == [("콩", "high")]


def test_eleven_notes_keep_ten_and_drop_lowest_without_merging():
    notes = [PurumaNote(f"interest:주제{i}", "interest", f"주제{i}", "medium", i, i) for i in range(1, 10)]
    notes.append(PurumaNote("interest:빵", "interest", "빵", "low", 10, 10))
    assert len(notes) == 10
    result = merge_puruma_notes(notes, [PurumaNote("promise:축제", "promise", "시험 끝나면 꼭 축제 가자", "high", 11, 11)])
    assert len(result) == PURUMA_MAX_NOTES
    keys = {n.key for n in result}
    assert "interest:빵" not in keys and "promise:축제" in keys
    # 제거된 내용이 다른 기억에 합쳐지지 않는다(기타_기억 같은 요약 노트 없음).
    assert all("빵" not in n.value for n in result)
    assert not any(n.key.startswith("기타") for n in result)


def test_equal_importance_drops_oldest_first():
    notes = [PurumaNote(f"interest:t{i}", "interest", f"t{i}", "medium", i, i) for i in range(1, 11)]
    result = merge_puruma_notes(notes, [PurumaNote("interest:t11", "interest", "t11", "medium", 11, 11)])
    assert len(result) == 10 and "interest:t1" not in {n.key for n in result}


def test_externally_provided_notes_are_revalidated():
    dirty = [
        PurumaNote("interest:음악", "interest", "음악", "medium", 1, 1),
        PurumaNote("x", "unknown_field", "값", "medium", 1, 1),
        PurumaNote("interest:학번", "interest", "학번 20231234", "high", 1, 1),
        PurumaNote("interest:x", "interest", "값", "very_high", 1, 1),
        PurumaNote("interest:긴값", "interest", "가" * 100, "low", 1, 1),
    ]
    result = merge_puruma_notes(dirty, [])
    assert [n.key for n in result] == ["interest:음악", "interest:긴값"]
    assert len(result[1].value) == memory.PURUMA_VALUE_MAX_CHARS


def test_prompt_selection_orders_by_importance_and_caps_ten():
    notes = [PurumaNote(f"interest:m{i}", "interest", f"m{i}", "medium", i, i) for i in range(12)]
    notes.append(PurumaNote("nickname", "nickname", "콩", "high", 0, 0))
    selected = puruma_notes_for_prompt(notes, "오늘 수업 어땠어?")
    assert len(selected) == 10 and selected[0].field == "nickname"


def test_general_persona_memory_functions_are_unchanged():
    # 일반 페르소나용 규칙 추출은 기존 동작(이름 저장 포함)을 그대로 유지한다.
    keys = {note.key for note in memory.extract_rule_based("내 이름은 지우야. 나는 마카롱을 좋아해.")}
    assert "이름" in keys and any(key.startswith("선호_") for key in keys)
