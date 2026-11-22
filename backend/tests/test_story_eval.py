"""스토리 채팅 평가 실행기(scripts.story_eval) 테스트. 외부 API·네트워크를 쓰지 않는다.

- 집계 계산(통과율·대체 비율·장면별 위반·백분위수·토큰·의도 정확도·행동 통과율)
- dry-run 예상 호출 수와 계획(의도 예시 전부 1회씩, 행동 케이스 배치 규칙)
- 호출 상한(Budget)
- 리포트 형식(조건이 맨 위, report.json에 대사 원문 없음, 비교표)
- 서비스의 생성 기록(extra.generation)과 실행기 끝-끝(ASGI + 테스트 DB + 가짜 Gemini)
"""

from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import Message, StoryTurnRecord
from app.services import story_turn_service
from app.services.llm.base import LLMProvider, LLMResult
from app.services.story_scenes import get_project
from scripts.story_eval import plan as eval_plan
from scripts.story_eval.checks import CheckResult, Observation, case_status, run_checks, validate_check_spec
from scripts.story_eval.metrics import behavior_metrics, generation_metrics, intent_metrics, percentile
from scripts.story_eval.report import build_report, load_report, render_compare, render_summary, write_run
from scripts.story_eval.runner import Budget, BudgetExceeded, RunState, StoryEvalRunner, TurnMetaReader, extract_meta

SCENARIO = "scenario_draft_v1"


def rec(turn=1, provider="gemini", attempts=1, violations=(), prompt=100, completion=20, thinking=None, latency=500, **kw):
    record = {
        "suite": "quality", "project": "fridge", "turn": turn, "kind": kw.pop("kind", "free"), "status_code": kw.pop("status_code", 200),
        "provider": provider, "model": "m", "latency_ms": latency, "wall_ms": latency + 10, "safety_notice": False,
        "meta": {
            "attempts": attempts, "intent_id": kw.pop("intent_id", None), "fallback_reason": kw.pop("fallback_reason", None),
            "generation": {"calls": attempts or 2, "violations": list(violations), "prompt_tokens": prompt, "completion_tokens": completion, "thinking_tokens": thinking},
            "dialogue": kw.pop("dialogue", {}),
        },
    }
    record.update(kw)
    return record


# --------------------------------------------------------------------------- #
# 집계
# --------------------------------------------------------------------------- #
def test_percentile_nearest_rank():
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    values = list(range(1, 21))  # 1..20
    assert percentile(values, 50) == 10
    assert percentile(values, 95) == 19
    assert percentile([300, 100, 200], 50) == 200


def test_generation_metrics_rates_violations_tokens():
    records = [
        rec(1, attempts=1, latency=100),
        rec(2, attempts=2, violations=["style_polite"], latency=300),
        rec(3, provider="fallback", attempts=0, violations=["repetition", "repetition"], fallback_reason="response_control:repetition,repetition", latency=50),
        rec(4, attempts=1, latency=200, thinking=5),
        rec(5, status_code=504, provider=None),
        rec(6, kind="fixed", provider="fixed", attempts=None),
        rec(7, provider="safety", safety_notice=True),
    ]
    m = generation_metrics(records)
    assert m["llm_turns"] == 5  # fixed·위기 제외, HTTP 오류 포함
    assert m["http_errors"] == 1 and m["http_error_codes"] == {"504": 1}
    assert m["generated_turns"] == 4
    assert m["first_pass"] == 2 and m["corrected_pass"] == 1 and m["fallback"] == 1
    assert m["first_pass_rate"] == 0.5
    assert m["pass_after_correction_rate"] == 0.75
    assert m["fallback_rate"] == 0.25
    assert m["fallback_reasons"] == {"response_control:repetition,repetition": 1}
    assert m["violations_by_scene"] == {"2": {"style_polite": 1}, "3": {"repetition": 2}}
    assert m["violations_total"] == {"repetition": 2, "style_polite": 1}
    # 지연은 AI 응답 턴만(대체 응답 제외): 100, 300, 200
    assert m["latency_ms"]["p50"] == 200 and m["latency_ms"]["p95"] == 300
    # 토큰은 모든 기록 합계(실패·대체 시도 포함), 생각 토큰은 보고된 값만
    assert m["tokens"]["prompt_tokens"] == 700
    assert m["tokens"]["thinking_tokens"] == 5


def test_generation_metrics_mock_is_not_measured():
    m = generation_metrics([rec(1, provider="mock", attempts=0, prompt=None, completion=None)])
    assert m["generated_turns"] == 0 and m["mock_turns"] == 1
    assert m["first_pass_rate"] is None and m["fallback_rate"] is None
    assert m["tokens"]["prompt_tokens"] is None


def test_generation_metrics_qwen():
    records = [
        rec(1, dialogue={"qwen_attempted": True, "qwen_used": True, "qwen_latency_ms": 900}),
        rec(2, dialogue={"qwen_attempted": True, "qwen_used": False, "qwen_latency_ms": 25000, "fallback_reason": "qwen_timeout"}),
        rec(3, dialogue={"qwen_attempted": False}),
    ]
    q = generation_metrics(records)["qwen"]
    assert q["attempted"] == 2 and q["used"] == 1 and q["used_rate"] == 0.5
    assert q["fallback_reasons"] == {"qwen_timeout": 1}


def test_intent_metrics_accuracy_and_confusions():
    def irec(turn, expected, predicted, provider="gemini", example="예시"):
        return {"suite": "intent", "project": "fridge", "turn": turn, "kind": "free", "status_code": 200, "provider": provider,
                "expected_intent": expected, "example": example, "meta": {"intent_id": predicted}}

    m = intent_metrics([
        irec(1, "a", "a"), irec(1, "b", "a", example="헷갈림"), irec(2, "c", None, provider="fallback"),
        irec(2, "d", "d"), irec(3, "e", None, provider="mock"),
        {"suite": "intent", "project": "fridge", "turn": 1, "kind": "choice", "status_code": 200, "provider": "gemini", "expected_intent": None, "meta": None},
    ])
    assert m["samples"] == 4 and m["mock"] == 1  # Mock은 분모에서 제외, 필러(choice) 제외
    assert m["correct"] == 2 and m["accuracy"] == 0.5
    assert m["answered"] == 3 and m["accuracy_answered"] == round(2 / 3, 4)
    assert m["no_prediction"] == 1 and m["fallback"] == 1
    assert m["by_turn"]["1"] == {"samples": 2, "answered": 2, "correct": 1, "accuracy": 0.5, "accuracy_answered": 0.5}
    assert [(c["input"], c["expected"], c["predicted"]) for c in m["confusions"]] == [("헷갈림", "b", "a"), ("예시", "c", None)]


def test_behavior_metrics_excludes_inconclusive_from_pass_rate():
    ok = {"passed": True}
    bad = {"passed": False}
    m = behavior_metrics([
        {"id": "a", "status": "pass", "auto": [ok], "tags": ["privacy"]},
        {"id": "b", "status": "fail", "auto": [ok, bad], "tags": ["privacy"]},
        {"id": "c", "status": "inconclusive", "auto": [ok], "tags": ["romance"]},
        {"id": "d", "status": "needs_review", "auto": [], "tags": ["romance"]},
        {"id": "e", "status": "not_run", "auto": [], "tags": []},
    ])
    assert m["auto_checked"] == 2 and m["auto_all_passed"] == 1 and m["auto_pass_rate"] == 0.5
    assert m["failed_cases"] == ["b"]
    assert m["by_tag"]["privacy"] == {"pass": 1, "fail": 1}


# --------------------------------------------------------------------------- #
# 계획과 예상 호출 수
# --------------------------------------------------------------------------- #
def test_dry_run_estimate_counts():
    plans = eval_plan.quality_plans(["fridge", "cloud"])
    est = eval_plan.estimate_calls(plans, repeat=2, story_attempts=2, http_attempts=2, qwen=True)
    rows = {(r["suite"], r["project"]): r for r in est["rows"]}
    fridge, cloud = rows[("quality", "fridge")], rows[("quality", "cloud")]
    assert fridge["llm_turns"] == 18 and fridge["fixed_turns"] == 2  # 9 LLM + 10턴 고정, 2회 반복
    assert fridge["min_calls"] == 36  # 18 생성 + 18 Qwen
    assert fridge["max_calls"] == 18 * (2 * 2 + 1)
    assert cloud["min_calls"] == 18 and cloud["max_calls"] == 18 * 4  # 구름섬은 Qwen 없음
    assert est["total_max_calls"] == 90 + 72
    no_qwen = eval_plan.estimate_calls(plans, repeat=1, story_attempts=1, http_attempts=1, qwen=False)
    assert no_qwen["total_min_calls"] == no_qwen["total_max_calls"] == 18


def test_intent_plan_sends_every_example_once():
    for project in ("fridge", "cloud"):
        samples = eval_plan.intent_samples(project)
        expected = sorted((t, text, intent) for t, rows in samples.items() for text, intent in rows)
        sent = sorted(
            (s.turn, s.text, s.expected_intent)
            for p in eval_plan.intent_plans([project]) for s in p.steps if s.expected_intent
        )
        assert sent == expected
        for p in eval_plan.intent_plans([project]):
            assert [s.turn for s in p.steps] == list(range(1, len(p.steps) + 1))  # 턴을 건너뛰지 않는다


def test_behavior_plan_packing_rules():
    plans, cases = eval_plan.behavior_plans(["fridge", "cloud"])
    runnable = {c.id for c in cases if c.runnable}
    placed = [cid for p in plans for s in p.steps for cid in s.case_ids]
    assert sorted(placed) == sorted(runnable)  # 실행 가능 케이스는 정확히 한 번씩
    for p in plans:
        advancing = [s.turn for s in p.steps if s.kind != "crisis"]
        assert advancing == list(range(1, len(advancing) + 1))  # 한 장면에 진행 입력 하나, 순서대로
        for i, s in enumerate(p.steps):
            if s.kind == "crisis":
                assert p.steps[i + 1].turn == s.turn  # 위기 입력 뒤에 같은 턴 입력이 이어진다
    fixed = [s for p in plans for s in p.steps if s.kind == "fixed"]
    assert all(s.turn == 10 for s in fixed)
    assert {"fridge_test_promo_10", "fridge_test_trailer_stop"} <= {c for s in fixed for c in s.case_ids}
    # 필수 범주가 두 작품 모두에 있다
    for project in ("fridge", "cloud"):
        tags = {t for c in cases if c.project == project and c.runnable for t in c.tags}
        assert {"prompt_leak", "role_change", "romance", "real_world", "privacy", "offtopic", "crisis"} <= tags, project


def test_behavior_definitions_cover_source_ids():
    for project, path in (("fridge", "data/fridge_data/tests/fridge_chat_test_cases.json"), ("cloud", "data/cloud_data/tests/cloud_chat_test_cases.json")):
        source = json.loads((eval_plan.REPO_ROOT / path).read_text(encoding="utf-8"))
        ids = {c.id for c in eval_plan.load_behavior_cases(project) if c.origin == "source"}
        assert ids == {c["id"] for c in source["cases"]}


# --------------------------------------------------------------------------- #
# 자동 검사
# --------------------------------------------------------------------------- #
def test_checks_use_ai_lines_only_and_statuses():
    obs = Observation("fridge", 4, 200, "gemini", replies=[("냉장고 회장", "흠, 알겠네."), ("냉장고 회장", "(고정) 고맙습니다요.")], fixed_lines_appended=1, nickname="민트")
    results = run_checks(obs, [{"type": "no_polite"}, {"type": "not_contains", "values": ["고정"]}, {"type": "max_sentences", "value": 3}])
    assert all(r.passed for r in results)  # 뒤에 붙은 장면 고정 대사는 검사하지 않는다
    assert case_status(obs, results, manual=True) == "needs_review"
    assert case_status(obs, results, manual=False) == "pass"
    polite = Observation("cloud", 2, 200, "gemini", replies=[("나나", "괜찮아요.")])
    failed = run_checks(polite, [{"type": "no_polite"}])
    assert not failed[0].passed and case_status(polite, failed, manual=True) == "fail"
    fallback = Observation("cloud", 2, 200, "fallback", replies=[("나나", "괜찮아요.")])
    assert case_status(fallback, run_checks(fallback, [{"type": "no_polite"}]), manual=False) == "inconclusive"
    assert case_status(Observation("cloud", 2, 503, None), [], manual=False) == "error"
    crisis = Observation("fridge", 4, 200, "safety", safety_notice=True, advanced=False)
    assert all(r.passed for r in run_checks(crisis, [{"type": "safety_notice", "value": True}, {"type": "advanced", "value": False}]))


def test_check_spec_validation():
    with pytest.raises(ValueError):
        validate_check_spec({"type": "llm_magic"})
    with pytest.raises(ValueError):
        validate_check_spec({"type": "max_speakers"})
    validate_check_spec({"type": "no_url"})


# --------------------------------------------------------------------------- #
# 호출 상한
# --------------------------------------------------------------------------- #
def test_budget_stops_before_exceeding():
    budget = Budget(max_calls=9, story_attempts=2, http_attempts=2, qwen=True)
    assert budget.step_max("fridge") == 5 and budget.step_max("cloud") == 4
    budget.check("fridge")
    budget.charge("fridge", {"generation": {"calls": 1}, "dialogue": {"qwen_attempted": True}}, "gemini")
    assert budget.used_upper == 3 and budget.generation_calls == 1 and budget.qwen_calls == 1
    budget.check("cloud")  # 3 + 4 <= 9
    budget.check("fridge")  # 3 + 5 <= 9
    budget.charge("cloud", {"generation": {"calls": 2}, "dialogue": {}}, "gemini")  # +4 → 7
    with pytest.raises(BudgetExceeded):
        budget.check("cloud")  # 7 + 4 > 9


def test_budget_boundary_and_unknown_meta():
    budget = Budget(max_calls=8, story_attempts=2, http_attempts=2, qwen=True)
    budget.charge("fridge", {"generation": {"calls": 1}, "dialogue": {"qwen_attempted": True}}, "gemini")  # 3
    budget.check("fridge")  # 3 + 5 == 8 → 허용
    budget.charge("cloud", None, "gemini")  # 메타 없음 → 최악(4)으로 센다
    assert budget.used_upper == 7
    with pytest.raises(BudgetExceeded):
        budget.check("cloud")
    budget.charge("cloud", None, "mock")  # Mock은 호출이 아니다
    assert budget.used_upper == 7
    assert Budget(None, 2, 2, False).check("fridge") is None  # 상한 없음


def test_extract_meta_drops_dialogue_text():
    extra = {
        "lines": [{"speaker": "회장", "text": "비밀 대사"}], "reaction": "반응 원문", "attempts": 2, "intent_id": "x",
        "control_violations": ["style_polite"], "fixed_lines_appended": 1, "story_fallback": {"reason": "provider_http_503"},
        "generation": {"calls": 2, "violations": ["style_polite"], "prompt_tokens": 10, "completion_tokens": 3, "thinking_tokens": None, "config": {"thinking_level": "minimal"}},
        "dialogue": {"qwen_attempted": True, "qwen_used": False, "fallback_reason": "qwen_timeout"},
    }
    meta = extract_meta(extra)
    assert "비밀 대사" not in json.dumps(meta, ensure_ascii=False) and "반응 원문" not in json.dumps(meta, ensure_ascii=False)
    assert meta["fallback_reason"] == "provider_http_503" and meta["generation"]["calls"] == 2


# --------------------------------------------------------------------------- #
# 서비스 생성 기록 + 실행기 끝-끝
# --------------------------------------------------------------------------- #
class ScriptedGemini(LLMProvider):
    """스토리 JSON을 돌려주는 가짜 Gemini. polite_first_turns의 첫 시도는 존댓말로 위반시키고, fail_turns는 JSON을 깬다."""

    name = "gemini"
    chat_model = "fake-eval-model"
    thinking_level = "minimal"
    http_attempts = 2
    supports_json_schema = True

    def __init__(self, project: str, polite_first_turns=(), fail_turns=()):
        self.project = get_project(project, SCENARIO)
        self.polite_first_turns = set(polite_first_turns)
        self.fail_turns = set(fail_turns)
        self.calls = 0
        self.turn_attempts: dict[int, int] = {}

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False, json_schema=None):
        self.calls += 1
        prompt = "\n".join(m["content"] for m in messages)
        turn = max(i for i, s in enumerate(self.project.scenes) if s.input_mode != "none" and s.title and s.title in prompt)
        attempt = self.turn_attempts[turn] = self.turn_attempts.get(turn, 0) + 1
        intents = re.findall(r"\[((?:fridge|cloud)_t\d\d_i\d\d)\]", prompt)
        if turn in self.fail_turns:
            text = "JSON 아님"
        else:
            words = [
                "흠흠, 좋네. 문부터 닫게.", "수상하군. 증거는 차차 보여 주지.", "두고 보세. 규칙은 규칙일세.",
                "허허, 배짱 좋군. 뉴스를 기다려 보게.", "냉기부터 지키게. 소식은 곧 올 걸세.", "어허, 라면은 그만 먹게.",
                "판매자 이름을 확인하게. 서두르지 말고.", "오늘 밤 손님은 들이지 말게.", "쉿, 숨을 죽이게.",
            ]
            body = words[turn % len(words)]
            if attempt == 1 and turn in self.polite_first_turns:
                body += " 고마워요."
            text = json.dumps({"lines": [{"speaker": self.project.speakers[0], "text": body}], "reaction": "끄덕", "intent_id": intents[0] if intents else "none"}, ensure_ascii=False)
        return LLMResult(text=text, provider=self.name, model=self.chat_model, latency_ms=3, prompt_tokens=100, completion_tokens=20, thinking_tokens=4)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


async def _extra_for_turn(conversation_id: str, turn: int) -> dict:
    async with SessionLocal() as db:
        record = (await db.execute(select(StoryTurnRecord).where(StoryTurnRecord.conversation_id == conversation_id, StoryTurnRecord.turn_index == turn))).scalar_one()
        return (await db.get(Message, record.assistant_message_id)).extra


async def test_generation_trace_recorded_for_success_and_fallback(client, monkeypatch):
    fake = ScriptedGemini("fridge", polite_first_turns={0}, fail_turns={1})
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    monkeypatch.setattr(settings, "fridge_qwen_dialogue_enabled", False)
    session = await client.post("/api/sessions", json={"display_name": "민트"})
    headers = {"X-Personal-Code": session.json()["personal_code"], "X-Story-Provider": "gemini"}
    cid = (await client.post("/api/story-chat/conversations", json={"project": "fridge", "scene_set": SCENARIO}, headers=headers)).json()["conversation_id"]

    first = await client.post(f"/api/story-chat/conversations/{cid}/turns", json={"request_id": "req-eval-0001", "turn": 0, "input": {"text": "앗 네 닫을게요"}}, headers=headers)
    assert first.status_code == 200 and first.json()["provider"] == "gemini"
    gen = (await _extra_for_turn(cid, 0))["generation"]
    assert gen["calls"] == 2 and gen["violations"] == ["style_polite"]
    assert gen["prompt_tokens"] == 200 and gen["completion_tokens"] == 40 and gen["thinking_tokens"] == 8
    assert gen["config"]["thinking_level"] == "minimal" and gen["config"]["http_attempts"] == 2
    assert "text" not in json.dumps(gen)  # 생성 기록에는 대사가 없다

    second = await client.post(f"/api/story-chat/conversations/{cid}/turns", json={"request_id": "req-eval-0002", "turn": 1, "input": {"text": "증거 있어요?"}}, headers=headers)
    assert second.status_code == 200 and second.json()["provider"] == "fallback"
    extra = await _extra_for_turn(cid, 1)
    assert extra["generation"]["calls"] == 2 and extra["generation"]["violations"] == ["format", "format"]
    assert extra["generation"]["prompt_tokens"] == 200  # 실패한 시도의 토큰도 센다
    assert extra["attempts"] == 0 and extra["story_fallback"]["reason"].startswith("response_control:")  # 기존 필드 의미 유지


async def test_runner_end_to_end_writes_report(client, monkeypatch, tmp_path):
    fake = ScriptedGemini("fridge", polite_first_turns={2}, fail_turns={4})
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    monkeypatch.setattr(settings, "fridge_qwen_dialogue_enabled", False)
    plans = eval_plan.quality_plans(["fridge"])
    budget = Budget(max_calls=100, story_attempts=2, http_attempts=2, qwen=False)
    reader = TurnMetaReader(settings.database_url)
    runner = StoryEvalRunner(client, reader, budget, expect_provider="gemini", log=lambda *_: None)
    state = RunState()
    try:
        await runner.run_conversation(plans[0], repeat=1, index=0, state=state)
    finally:
        await reader.close()
    assert len(state.records) == 10 and state.records[-1]["provider"] == "fixed" and state.records[-1]["finished"]
    assert fake.calls == 11  # 9턴 + 교정 1회 + 실패 턴 추가 1회
    assert budget.generation_calls == 11 and budget.used_upper == 22

    report = build_report(
        run={"label": "fake", "started_at": "2026-11-22T00:00:00+09:00", "finished_at": "2026-11-22T00:01:00+09:00", "suites": ["quality"], "projects": ["fridge"], "repeat": 1, "scene_set": SCENARIO, "status": "completed", "stop_reason": None},
        server={"provider": "gemini", "chat_model": "fake-eval-model", "degraded": False},
        assumed={"story_generation_attempts": 2, "http_attempts": 2, "fridge_qwen_dialogue_enabled": False},
        budget=budget.as_dict(),
        plan_estimate=eval_plan.estimate_calls(plans, repeat=1, story_attempts=2, http_attempts=2, qwen=False),
        records=state.records,
        behavior=[],
    )
    q = report["metrics"]["quality"]["fridge"]
    assert q["generated_turns"] == 9 and q["first_pass"] == 7 and q["corrected_pass"] == 1 and q["fallback"] == 1
    assert q["violations_by_scene"] == {"3": {"style_polite": 1}, "5": {"format": 2}}
    assert q["tokens"]["prompt_tokens"] == 1100
    assert report["conditions"]["observed"]["thinking_level"] == "minimal"
    assert report["conditions"]["warnings"] == []

    paths = write_run(report, [], tmp_path / "run")
    saved = paths["report"].read_text(encoding="utf-8")
    assert "증거는 차차" not in saved and "숨을 죽이게" not in saved  # 대사 원문 없음
    summary = paths["summary"].read_text(encoding="utf-8")
    assert summary.index("## 실행 조건") < summary.index("## 1. 10턴 진행 품질")
    assert "fake-eval-model" in summary and "minimal" in summary
    loaded = load_report(paths["report"])
    other = json.loads(json.dumps(loaded))
    other["run"]["label"] = "other"
    other["metrics"]["quality"]["fridge"]["first_pass_rate"] = 0.5
    table = render_compare([loaded, other])
    assert "| 지표 | fake | other |" in table and "품질 · 첫 시도 통과율 | 77.8% | 50.0% |" in table


async def test_runner_stops_at_call_cap(client, monkeypatch):
    fake = ScriptedGemini("fridge")
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    monkeypatch.setattr(settings, "fridge_qwen_dialogue_enabled", False)
    plans = eval_plan.quality_plans(["fridge"])
    budget = Budget(max_calls=8, story_attempts=2, http_attempts=2, qwen=False)
    reader = TurnMetaReader(settings.database_url)
    runner = StoryEvalRunner(client, reader, budget, expect_provider="gemini", log=lambda *_: None)
    state = RunState()
    try:
        with pytest.raises(BudgetExceeded):
            await runner.run_conversation(plans[0], repeat=1, index=0, state=state)
    finally:
        await reader.close()
    # 턴당 최대 4회: 0 → 2 → 4 (다음 4를 더하면 8 이하라 3번째 턴 허용) → 6 (6+4 > 8 이므로 멈춤)
    assert fake.calls == 3 and len(state.records) == 3 and budget.used_upper == 6


def test_render_summary_marks_mock_warning():
    records = [rec(1, provider="mock", attempts=0, prompt=None, completion=None)]
    report = build_report(
        run={"label": "m", "started_at": "t", "finished_at": "t", "suites": ["quality"], "projects": ["fridge"], "repeat": 1, "scene_set": SCENARIO, "status": "completed", "stop_reason": None},
        server={"provider": "mock", "chat_model": "mock-persona-v1"}, assumed={}, budget=Budget(None, 2, 2, False).as_dict(),
        plan_estimate={"total_min_calls": 0, "total_max_calls": 0}, records=records, behavior=[],
    )
    text = render_summary(report)
    assert text.startswith("# 스토리 채팅 평가 리포트 · m\n\n## 실행 조건")
    assert "Mock 공급자 실행" in text


def test_check_result_dict_shape():
    assert CheckResult("no_url", True).as_dict() == {"type": "no_url", "passed": True, "detail": ""}
