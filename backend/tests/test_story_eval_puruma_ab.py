"""평가 실행기의 푸르마 스위트와 두 모델 번갈아 실행(ab) 테스트. 외부 API·네트워크를 쓰지 않는다.

- 푸르마 계획: 10턴 품질 입력(홍보 R1~R3·CC 분기·10턴 진로), 주제·태도 정답 세트 매핑, 행동 케이스
- 집계: 태도 정확도·위기 우선 케이스, 푸르마 진행 신호, 실패 시각 분포, 서버 로그의 HTTP 시도
- 실행: ASGI + 테스트 DB + 가짜 Gemini로 푸르마 10턴 끝-끝, A·B 번갈아 실행 순서와 함께 멈추기
"""

from __future__ import annotations

import argparse
import json

import pytest

from app.core.config import settings
from app.services import puruma_state, story_turn_service
from app.services.llm.base import LLMProvider, LLMResult
from app.services.puruma_scenes import TURNS
from scripts.story_eval import ab as eval_ab
from scripts.story_eval import plan as eval_plan
from scripts.story_eval.metrics import (
    attitude_metrics,
    failure_events,
    failure_timeline,
    http_log_summary,
    parse_gemini_http_log,
    puruma_signals,
    time_bucket,
)
from scripts.story_eval.report import build_report, render_compare, render_summary
from scripts.story_eval.runner import Budget, BudgetExceeded, RunAborted, RunState, StoryEvalRunner, TurnMetaReader, extract_meta


# --------------------------------------------------------------------------- #
# 계획
# --------------------------------------------------------------------------- #
def _choice_id(turn: int, index: int) -> str:
    return TURNS[turn - 1].choices[index].id


def test_puruma_quality_plan_triggers_promos_cc_and_path():
    """quality 입력을 서버 상태 규칙(LLM 없음)으로 굴려 R1·R2·R3·CC·진로가 실제로 나오는지 확인한다."""
    (plan,) = eval_plan.quality_plans(["puruma"])
    assert [s.turn for s in plan.steps] == list(range(1, 11))
    assert {s.kind for s in plan.steps} == {"choice", "free"} and plan.llm_steps() == 10  # 10턴도 입력 턴(고정 연출 없음)
    views: list[puruma_state.TurnView] = []
    promos, cc_lines, path = [], 0, None
    for step in plan.steps:
        turn = step.turn - 1
        choice = _choice_id(step.turn, step.choice_index) if step.kind == "choice" else None
        planned = puruma_state.plan_turn(views, turn, choice, step.text or "", [])
        if planned.promo:
            promos.append(planned.promo.id)
        cc_lines += puruma_state.CC_SEED_LINE in planned.appended
        path = planned.path or path
        # 자유 입력은 분류를 '중립·일상'으로 둔다(가장 불리한 경우에도 CC 조건을 넘는지 본다).
        views.append(puruma_state.TurnView(turn, choice, None, None, planned.promo.id if planned.promo else None, planned.path))
    assert promos == ["rag_dining_cafeteria_menu", "rag_clubs_yu_general_union", "rag_library_central", "rag_career_center"]
    assert cc_lines == 1 and path == "career"
    assert puruma_state.judge(puruma_state.fold(views)) == "cc_pruma"


def test_puruma_intent_samples_map_labels_and_exclude_crisis_false_positive():
    samples, excluded = eval_plan.puruma_samples()
    topics = [s for s in samples if s.topic]
    attitudes = [s for s in samples if s.attitude]
    assert len(topics) == 35 and {s.topic for s in topics} == {i for i, _, _ in eval_plan_topic_ids()}
    assert len(attitudes) == 31 and [s.id for s in samples if s.safety] == ["t_attitude_safety_01"]
    # "너 혼자 해" → 공백 제거 시 "자해"가 들어 있어 서버 위기 판정에 걸린다(서비스 오탐). 채점에서 빼고 사유를 남긴다.
    assert [e["id"] for e in excluded] == ["t_attitude_21"] and "위기" in excluded[0]["reason"]

    plans = eval_plan.intent_plans(["puruma"])
    assert all(p.project == "puruma" and p.suite == "intent" for p in plans)
    first = plans[0].steps[0]
    assert first.kind == "crisis" and first.expected_safety and first.turn == 1
    for p in plans:
        regular = [s for s in p.steps if s.kind != "crisis"]
        assert [s.turn for s in regular] == list(range(1, len(regular) + 1)) and len(regular) <= 10
        assert all(s.kind == "free" and (s.expected_intent or s.expected_attitude) for s in regular)
    sent = [s.sample_id for p in plans for s in p.steps]
    assert len(sent) == len(set(sent)) == len(samples)


def eval_plan_topic_ids():
    from app.services.puruma_scenes import TOPIC_INTENTS

    return TOPIC_INTENTS


def test_puruma_behavior_cases_cover_required_categories():
    plans, cases = eval_plan.behavior_plans(["puruma"])
    tags = {t for c in cases for t in c.tags}
    assert {"prompt_leak", "role_change", "romance", "real_world", "privacy", "off_topic", "crisis"} <= tags
    assert all(c.origin == "eval_added" and c.runnable for c in cases)
    assert not any(check["type"] == "no_polite" for c in cases for check in c.auto_checks)  # 푸르마는 존댓말 캐릭터
    crisis = [s for p in plans for s in p.steps if s.kind == "crisis"]
    assert [s.case_ids for s in crisis] == [["puruma_eval_crisis"]]
    hardship = next(s for p in plans for s in p.steps if "puruma_eval_hardship_not_crisis" in s.case_ids)
    assert hardship.kind == "free"  # 일상적 힘듦은 위기 판정에 걸리지 않아야 한다


def test_schedule_spreads_quality_repeats_and_estimate_counts_them():
    plans, _ = eval_plan.build_plans(["quality", "intent"], ["puruma"])
    order = eval_plan.schedule(plans, repeat=1, quality_repeat=2)
    assert [(p.suite, r) for p, r, _ in order][0] == ("quality", 1)
    assert [(p.suite, r) for p, r, _ in order][-1] == ("quality", 2)
    assert sum(1 for p, _, _ in order if p.suite == "intent") == len(plans) - 1
    est = eval_plan.estimate_calls(plans, repeat=1, quality_repeat=2, story_attempts=2, http_attempts=2, qwen=False)
    quality = next(r for r in est["rows"] if r["suite"] == "quality")
    assert quality["conversations"] == 2 and quality["llm_turns"] == 20 and quality["max_calls"] == 80
    assert est["assumptions"]["quality_repeat"] == 2


# --------------------------------------------------------------------------- #
# 집계
# --------------------------------------------------------------------------- #
def _arec(expected, predicted, provider="gemini", **kw):
    return {"suite": "intent", "project": "puruma", "turn": 1, "kind": "free", "status_code": 200, "provider": provider,
            "expected_attitude": expected, "sample_id": "x", "example": "예시", "meta": {"puruma": {"attitude": predicted}}, **kw}


def test_attitude_metrics_accuracy_confusion_and_override():
    records = [
        _arec("중립", "중립"), _arec("중립", "응원·도움"), _arec("퉁명·부정", "퉁명·부정"), _arec("응원·도움", None, provider="fallback"),
        _arec("중립", "중립", provider="mock"),
        {"suite": "intent", "project": "puruma", "turn": 1, "kind": "crisis", "expected_safety": True, "safety_notice": True, "status_code": 200},
    ]
    m = attitude_metrics(records)
    assert m["samples"] == 4 and m["correct"] == 2 and m["accuracy"] == 0.5 and m["answered"] == 3
    assert m["mock"] == 1 and m["fallback"] == 1
    assert m["confusion"]["중립"] == {"중립": 1, "응원·도움": 1} and m["confusion"]["응원·도움"] == {"(없음)": 1}
    assert m["override_cases"] == 1 and m["override_safety_notice"] == 1


def test_puruma_signals_and_failure_timeline():
    def r(turn, **kw):
        base = {"suite": "quality", "project": "puruma", "turn": turn, "kind": "choice", "status_code": 200, "provider": "gemini",
                "repeat": 1, "conversation": 0, "meta": {"fixed_lines_appended": 0, "puruma": {}}}
        base.update(kw)
        return base
    records = [
        r(3, promo_id="rag_dining_cafeteria_menu", at="2026-11-22T14:03:00+09:00"),
        r(5, promo_id="rag_library_central", kind="free", provider="fallback", at="2026-11-22T14:07:59+09:00",
          meta={"fallback_reason": "provider_http_503", "generation": {"calls": 1}}),
        r(7, choice_id="c4_t7_c", meta={"fixed_lines_appended": 1}, at="2026-11-22T14:12:00+09:00"),
        r(10, promo_id="rag_career_center", ending="cc_pruma", meta={"puruma": {"path": "career"}}, at="2026-11-22T14:15:00+09:00"),
    ]
    s = puruma_signals(records)
    assert s["promo_by_rule"] == {"R1": 1, "R2": 1, "R3": 1} and s["cc_branch_turns"] == 1 and s["cc_line_appended"] == 1
    assert s["final_paths"] == {"career": 1} and s["endings"] == {"cc_pruma": 1}
    events = failure_events(records)
    assert [(e["at"], e["kind"], e["turn"]) for e in events] == [("2026-11-22T14:07:59+09:00", "provider_http_503", 5)]
    timeline = failure_timeline(records)
    assert timeline["buckets"] == {"2026-11-22 14:00": {"llm_turns": 2, "provider_http_503": 1}, "2026-11-22 14:10": {"llm_turns": 2}}
    assert time_bucket(None) == "unknown"


def test_parse_gemini_http_log_counts_absorbed_503_and_timeouts():
    lines = [
        "2026-11-22 14:00:01,100 | INFO    | app.services.llm.gemini_provider | provider=gemini model=m operation=generateContent attempt=1 status=503 headers_ms=5 latency_ms=9",
        "2026-11-22 14:00:01,101 | WARNING | app.services.llm.gemini_provider | provider=gemini model=m operation=generateContent attempt=1/2 status=503 will_retry=true error_status=UNAVAILABLE",
        "2026-11-22 14:00:02,200 | INFO    | app.services.llm.gemini_provider | provider=gemini model=m operation=generateContent attempt=2 status=200 headers_ms=5 latency_ms=900",
        "2026-11-22 14:11:00,000 | WARNING | app.services.llm.gemini_provider | provider=gemini model=m operation=generateContent attempt=1 error=ReadTimeout phase=before_headers headers_ms=None latency_ms=30000",
        "2026-11-22 14:11:05,000 | INFO    | app.services.llm.gemini_provider | provider=gemini model=m operation=batchEmbedContents attempt=1 status=200 headers_ms=5 latency_ms=9",
        "2026-11-22 14:11:06,000 | INFO    | app.services.story_turn_service | 다른 로그",
    ]
    events = parse_gemini_http_log(lines)
    assert [(e["at"], e["attempt"], e["status"]) for e in events] == [
        ("2026-11-22T14:00:01+09:00", 1, 503), ("2026-11-22T14:00:02+09:00", 2, 200), ("2026-11-22T14:11:00+09:00", 1, "ReadTimeout"),
    ]
    summary = http_log_summary(events)
    assert summary["requests"] == 3 and summary["retries"] == 1 and summary["by_status"] == {"200": 1, "503": 1, "ReadTimeout": 1}
    assert summary["buckets"] == {"2026-11-22 14:00": {"requests": 2, "503": 1}, "2026-11-22 14:10": {"requests": 1, "ReadTimeout": 1}}
    assert len(summary["non_200"]) == 2


def test_extract_meta_keeps_puruma_codes_only():
    meta = extract_meta({"lines": [{"speaker": "푸르마", "text": "대사"}], "attempts": 1,
                         "puruma": {"topic": "topic_study", "attitude": "중립", "emotion": "happy", "promo_id": None, "path": None, "notes": ["x"]}})
    assert meta["puruma"] == {"topic": "topic_study", "attitude": "중립", "emotion": "happy", "promo_id": None, "path": None}
    assert "대사" not in json.dumps(meta, ensure_ascii=False)
    assert "puruma" not in extract_meta({"attempts": 1})


def _report(label, records, env=None, http_log=None, behavior=()):
    return build_report(
        run={"label": label, "started_at": "2026-11-22T14:00:00+09:00", "finished_at": "2026-11-22T15:00:00+09:00", "suites": ["quality", "intent"],
             "projects": ["fridge", "puruma"], "repeat": 1, "scene_set": "x", "status": "completed", "stop_reason": None},
        server={"provider": "gemini", "chat_model": label, "degraded": False}, assumed={}, budget=Budget(10, 2, 2, False).as_dict(),
        plan_estimate={"total_min_calls": 0, "total_max_calls": 0, "assumptions": {"quality_repeat": 2}}, records=records, behavior=list(behavior),
        server_env=env, http_log=http_log,
    )


def test_report_server_env_on_top_totals_and_compare_timeline():
    def q(project, provider="gemini", at="2026-11-22T14:01:00+09:00", reason=None):
        return {"suite": "quality", "project": project, "turn": 1, "kind": "free", "status_code": 200, "provider": provider, "at": at,
                "latency_ms": 100, "wall_ms": 110, "meta": {"attempts": 1 if provider == "gemini" else 0, "fallback_reason": reason, "generation": {"calls": 1}}}
    env = {"LLM_PROVIDER": "gemini", "GEMINI_THINKING_LEVEL": "minimal", "STORY_GENERATION_ATTEMPTS": "2", "GEMINI_HTTP_ATTEMPTS": "2",
           "LLM_TIMEOUT_SECONDS": "30.0", "FRIDGE_QWEN_DIALOGUE_ENABLED": "false", "LLM_PROBE_ON_STARTUP": "false", "SEED_ON_STARTUP": "false"}
    a = _report("model-a", [q("fridge"), q("puruma", "fallback", reason="provider_http_503")], {**env, "GEMINI_CHAT_MODEL": "model-a"},
                http_log=http_log_summary(parse_gemini_http_log(["2026-11-22 14:01:00,000 | INFO    | app.services.llm.gemini_provider | provider=gemini model=model-a operation=generateContent attempt=1 status=503 headers_ms=1 latency_ms=1"])))
    b = _report("model-b", [q("fridge"), q("puruma")], {**env, "GEMINI_CHAT_MODEL": "model-b"})
    assert a["metrics"]["quality"]["total"]["fallback_rate"] == 0.5 and a["metrics"]["quality"]["total"]["generated_turns"] == 2
    summary = render_summary(a)
    assert summary.index("## 서버 설정") < summary.index("## 실행 조건") < summary.index("## 1. 10턴 진행 품질")
    assert "| LLM_TIMEOUT_SECONDS | 30.0 |" in summary and "provider_http_503" in summary
    table = render_compare([a, b])
    assert table.index("## 서버 설정") < table.index("## 실행 조건") < table.index("## Gemini HTTP 시도 요약")
    assert "모델(GEMINI_CHAT_MODEL) 외 설정은 모두 같습니다." in table
    assert "## 합계(세 작품 표본 합산)" in table and "| 품질 · 대체 응답 비율 | 50.0% | 0.0% |" in table
    assert "| 전 스위트 · 대체 사유 provider_http_503 | 1 | 0 |" in table
    assert "| 2026-11-22 14:00 | 1 / 2 (provider_http_503 1) | 0 / 2 |" in table
    b2 = _report("model-b", [q("fridge")], {**env, "GEMINI_CHAT_MODEL": "model-b", "GEMINI_HTTP_ATTEMPTS": "1"})
    assert "모델 외 설정이 다릅니다: GEMINI_HTTP_ATTEMPTS" in render_compare([a, b2])


# --------------------------------------------------------------------------- #
# 끝-끝: 푸르마 10턴
# --------------------------------------------------------------------------- #
class ScriptedPuruma(LLMProvider):
    """푸르마 스키마(emotion·attitude·intent_id enum)에 맞춰 답하는 가짜 Gemini."""

    name = "gemini"
    chat_model = "fake-puruma-model"
    thinking_level = "minimal"
    http_attempts = 2
    supports_json_schema = True
    lines = ("우와, 선배 덕분에 힘이 나요!", "히히힝, 그렇게 해 볼게요.", "선배랑 같이라면 안 무서워요!", "정말요? 메모해 둘게요.",
             "또각또각, 발굽이 들썩여요!", "오늘도 한 걸음 갔어요.", "그런 방법도 있었군요!", "조금 걱정되지만 해 볼게요.",
             "선배는 역시 든든해요.", "캠퍼스가 덜 넓게 느껴져요!")

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, json_mode=False, json_schema=None):
        self.calls += 1
        topics = json_schema["properties"]["intent_id"]["enum"]
        text = json.dumps({"lines": [{"speaker": "푸르마", "text": self.lines[self.calls % len(self.lines)]}], "reaction": "끄덕",
                           "intent_id": topics[0], "attitude": "응원·도움", "emotion": "happy"}, ensure_ascii=False)
        return LLMResult(text=text, provider=self.name, model=self.chat_model, latency_ms=3, prompt_tokens=100, completion_tokens=20, thinking_tokens=4)

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        yield ""


async def test_runner_puruma_quality_end_to_end(client, monkeypatch):
    fake = ScriptedPuruma()
    monkeypatch.setattr(story_turn_service, "get_llm", lambda: fake)
    (plan,) = eval_plan.quality_plans(["puruma"])
    budget = Budget(max_calls=100, story_attempts=2, http_attempts=2, qwen=False)
    reader = TurnMetaReader(settings.database_url)
    runner = StoryEvalRunner(client, reader, budget, expect_provider="gemini", log=lambda *_: None)
    state = RunState()
    try:
        await runner.run_conversation(plan, repeat=1, index=0, state=state)
    finally:
        await reader.close()
    records = state.records
    assert len(records) == 10 and all(r["status_code"] == 200 and r["provider"] == "gemini" for r in records)
    assert records[-1]["finished"] and records[-1]["ending"] == "cc_pruma"
    assert all(r["at"].endswith("+09:00") for r in records)
    free = [r for r in records if r["kind"] == "free"]
    assert all(r["meta"]["puruma"]["topic"] == "topic_study" and r["meta"]["puruma"]["attitude"] == "응원·도움" for r in free)
    signals = puruma_signals(records)
    assert signals["promo_by_rule"] == {"R1": 2, "R2": 1, "R3": 1}
    assert signals["cc_branch_turns"] == 1 and signals["cc_line_appended"] == 1 and signals["final_paths"] == {"career": 1}


# --------------------------------------------------------------------------- #
# 번갈아 실행
# --------------------------------------------------------------------------- #
class _FakeRunner:
    def __init__(self, label, calls, fail_at=None, exc=None):
        self.label, self.calls, self.fail_at, self.exc = label, calls, fail_at, exc

    async def run_conversation(self, plan, *, repeat, index, state):
        self.calls.append((self.label, plan.suite, repeat, index))
        if self.fail_at is not None and len([c for c in self.calls if c[0] == self.label]) == self.fail_at:
            raise self.exc


def _sides(calls, fail=None):
    sides = []
    for label in ("A", "B"):
        side = eval_ab.Side(label, "http://x", "sqlite://")
        if fail and fail[0] == label:
            side.runner = _FakeRunner(label, calls, fail_at=fail[1], exc=fail[2])
        else:
            side.runner = _FakeRunner(label, calls)
        sides.append(side)
    return sides


async def test_run_alternating_orders_a_b_per_conversation():
    calls = []
    plans, _ = eval_plan.build_plans(["quality"], ["fridge", "puruma"])
    args = argparse.Namespace(repeat=1, quality_repeat=2)
    sides = _sides(calls)
    await eval_ab.run_alternating(sides, plans, args, log=lambda *_: None)
    assert [c[0] for c in calls] == ["A", "B"] * 4
    assert [c[1:] for c in calls[::2]] == [c[1:] for c in calls[1::2]]  # 같은 대화를 A 다음 B가 진행
    assert [c[2] for c in calls[::2]] == [1, 1, 2, 2]
    assert all(s.status == "completed" for s in sides)


@pytest.mark.parametrize("exc,status", [(BudgetExceeded("상한"), "stopped_by_budget"), (RunAborted("provider_quota_daily"), "aborted")])
async def test_run_alternating_stops_both_when_one_side_stops(exc, status):
    calls = []
    plans, _ = eval_plan.build_plans(["quality"], ["fridge", "puruma"])
    sides = _sides(calls, fail=("B", 2, exc))
    await eval_ab.run_alternating(sides, plans, argparse.Namespace(repeat=1, quality_repeat=None), log=lambda *_: None)
    assert [c[0] for c in calls] == ["A", "B", "A", "B"]
    assert sides[1].status == status and sides[0].status == "stopped_with_pair" and "B" in sides[0].stop_reason


def test_server_env_differs_only_in_model_and_hides_db():
    args = argparse.Namespace(provider="gemini", thinking_level="minimal", story_attempts=2, http_attempts=2, llm_timeout=30.0, gemini_base_url=None)
    a = eval_ab.server_env(args, "gemini-3.1-flash-lite", "sqlite+aiosqlite:////tmp/a.db")
    b = eval_ab.server_env(args, "gemini-3.5-flash-lite", "sqlite+aiosqlite:////tmp/b.db")
    assert {k for k in a if a[k] != b[k]} == {"GEMINI_CHAT_MODEL", "DATABASE_URL"}
    assert a["FRIDGE_QWEN_DIALOGUE_ENABLED"] == a["LLM_PROBE_ON_STARTUP"] == a["SEED_ON_STARTUP"] == "false"
    assert "DATABASE_URL" not in eval_ab.public_env(a) and not any("KEY" in k for k in a)


async def test_runner_stops_on_daily_quota_fallback(client, monkeypatch):
    """스토리 턴은 429를 고정 대사로 넘기므로 대체 사유가 일일 할당량이면 실행기가 멈춘다."""
    from app.services.llm.gemini_provider import GeminiQuotaError

    class Quota(ScriptedPuruma):
        async def generate(self, *a, **kw):
            raise GeminiQuotaError("daily", None)

    monkeypatch.setattr(story_turn_service, "get_llm", lambda: Quota())
    (plan,) = eval_plan.quality_plans(["puruma"])
    reader = TurnMetaReader(settings.database_url)
    runner = StoryEvalRunner(client, reader, Budget(100, 2, 2, False), expect_provider="gemini", log=lambda *_: None)
    state = RunState()
    try:
        with pytest.raises(RunAborted, match="provider_quota_daily"):
            await runner.run_conversation(plan, repeat=1, index=0, state=state)
    finally:
        await reader.close()
    assert len(state.records) == 1 and state.records[0]["provider"] == "fallback"


def test_budget_counts_actual_http_requests_from_server_log(tmp_path):
    log = tmp_path / "server.log"
    line = "2026-11-22 14:00:01,100 | INFO    | app.services.llm.gemini_provider | provider=gemini model=m operation=generateContent attempt={a} status={s} headers_ms=5 latency_ms=9\n"
    log.write_text(line.format(a=1, s=503) + line.format(a=2, s=200), encoding="utf-8")
    budget = Budget(max_calls=6, story_attempts=2, http_attempts=2, qwen=False, http_counter=lambda: eval_ab.count_generate_requests(log))
    budget.charge("puruma", {"generation": {"calls": 1}}, "gemini")
    assert budget.used_upper == 2 and budget.generation_calls == 1  # 보수적 추정(1×2)이 아니라 로그의 실제 요청 2회
    budget.check("puruma")  # 2 + 4 <= 6
    with log.open("a", encoding="utf-8") as f:
        f.write(line.format(a=1, s=200))
    budget.charge("puruma", None, "gemini")
    assert budget.used_upper == 3 and budget.as_dict()["counting"] == "server_log_http_requests"
    with pytest.raises(BudgetExceeded):
        budget.check("puruma")  # 3 + 4 > 6
    assert eval_ab.count_generate_requests(tmp_path / "missing.log") == 0
