"""냉장고·구름섬 결말 판정 (2026-11-22 기획 결정: 마지막에만 반영, 시나리오 제안값)."""

from __future__ import annotations

from app.services.story_judgement import TurnScores, judge_cloud, judge_fridge, score_tables


def _fridge_tables(values: dict[int, dict[str, int]]) -> dict[int, TurnScores]:
    return {turn: TurnScores(v, {}) for turn, v in values.items()}


def test_fridge_stage_thresholds_6_and_12():
    tables = _fridge_tables({t: {"a": 2, "b": 1, "c": 0, "d": -1} for t in range(9)})
    assert judge_fridge({t: "a" for t in range(9)}, tables) == ("fridge_rel_stage_3", 18)
    assert judge_fridge({t: "b" for t in range(9)}, tables) == ("fridge_rel_stage_2", 9)
    assert judge_fridge({0: "a", 1: "a", 2: "b"}, tables) == ("fridge_rel_stage_1", 5)
    assert judge_fridge({0: "a", 1: "a", 2: "a"}, tables)[0] == "fridge_rel_stage_2"  # 6점 경계
    assert judge_fridge({t: "a" for t in range(6)}, tables)[0] == "fridge_rel_stage_3"  # 12점 경계
    assert judge_fridge({t: "d" for t in range(9)}, tables) == ("fridge_rel_stage_1", -9)


def test_fridge_unknown_or_missing_intent_scores_zero():
    tables = _fridge_tables({0: {"a": 2}, 1: {"a": 2}})
    assert judge_fridge({0: None, 1: "없는 의도"}, tables) == ("fridge_rel_stage_1", 0)


def _cloud_tables() -> dict[int, TurnScores]:
    v = {"toto": (1, 1), "bibi": (1, -1), "nana": (-1, -1), "kiki": (-1, 1), "dudu": ("pull", 2)}
    tables = {t: TurnScores(dict(v), {}) for t in range(1, 9)}
    tables[9] = TurnScores({}, {})  # 10턴 예고편(입력 없음)
    return tables


def test_cloud_quadrants_and_center():
    tables = _cloud_tables()
    for kind, ending in [("toto", "cloud_result_toto"), ("bibi", "cloud_result_bibi"), ("nana", "cloud_result_nana"), ("kiki", "cloud_result_kiki")]:
        assert judge_cloud({t: kind for t in range(1, 9)}, tables)[0] == ending
    assert judge_cloud({t: "dudu" for t in range(1, 9)}, tables) == ("cloud_result_dudu", 0, 0)
    assert judge_cloud({1: "toto"}, tables) == ("cloud_result_dudu", 1, 1)  # 두 축 모두 ±1 이내


def test_cloud_balance_pulls_toward_zero_without_crossing():
    tables = _cloud_tables()
    # 토토 3번(3,3) → 두두(1,1) → 두두(0,0)이 되고 0을 넘지 않는다
    assert judge_cloud({1: "toto", 2: "toto", 3: "toto", 4: "dudu", 5: "dudu"}, tables)[1:] == (0, 0)
    # 토토 3번 + 두두 1번 = (1,1) → 두두
    assert judge_cloud({1: "toto", 2: "toto", 3: "toto", 4: "dudu"}, tables)[0] == "cloud_result_dudu"


def test_cloud_one_small_axis_is_not_center():
    tables = _cloud_tables()
    # X = -1, Y = 5: 한 축만 ±1 이내면 두두가 아니고 부호로 정한다 → 키키(-,+)
    assert judge_cloud({1: "kiki", 2: "toto", 3: "kiki", 4: "toto", 8: "kiki"}, tables) == ("cloud_result_kiki", -1, 5)


def test_cloud_zero_axis_follows_turn9_direction():
    tables = _cloud_tables()
    # X = 0, Y = 6: X 방향은 9턴(인덱스 8) 키키(-,+)의 X 부호 - → 키키
    assert judge_cloud({1: "kiki", 2: "toto", 3: "kiki", 4: "toto", 5: "toto", 8: "kiki"}, tables) == ("cloud_result_kiki", 0, 6)
    # 9턴이 토토(+,+)면 같은 점수라도 + 쪽 → 토토
    assert judge_cloud({1: "kiki", 2: "toto", 3: "kiki", 4: "toto", 5: "kiki", 8: "toto"}, tables) == ("cloud_result_toto", 0, 6)
    # 9턴이 균형형이면 + 쪽
    x, y = judge_cloud({1: "kiki", 2: "toto", 3: "kiki", 4: "toto", 5: "kiki", 6: "toto", 7: "toto", 8: "dudu"}, tables)[1:]
    assert x == 0 and y > 1
    assert judge_cloud({1: "kiki", 2: "toto", 3: "kiki", 4: "toto", 5: "kiki", 6: "toto", 7: "toto", 8: "dudu"}, tables)[0] == "cloud_result_toto"


def test_real_score_tables_match_scenario_doc():
    fridge = score_tables("fridge")
    cloud = score_tables("cloud")
    assert fridge is not None and cloud is not None
    assert sorted(fridge) == list(range(10)) and sorted(cloud) == list(range(10))
    # 냉장고 1턴: 사과하고 문을 닫음 +2, 고장 취급 -1, 버튼은 의도에 연결
    assert fridge[0].values["fridge_t01_i01"] == 2 and fridge[0].values["fridge_t01_i04"] == -1
    assert fridge[0].choices["fridge_t01_i01_btn"] == "fridge_t01_i01"
    # 구름섬 5턴은 결정적 장면이라 ±2, 균형형은 당기기 2
    assert cloud[4].values["cloud_t05_i01"] == (2, 2)
    assert cloud[4].values["cloud_t05_i05"] == ("pull", 2)
    assert cloud[0].values == {} and fridge[9].values == {}
