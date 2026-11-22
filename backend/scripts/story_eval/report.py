"""리포트 조립·저장·비교.

- report.json : 기계용. 턴 기록(대사 원문 없음)·지표·행동 결과·실행 조건.
- summary.md  : 사람이 읽는 요약 표. 실행 조건을 맨 위에 둔다.
- review.md / review.json : 행동 테스트의 입력과 응답 원문(사람 검토용). 로컬 eval_reports/에만 남는다(git 제외).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.story_eval.checks import case_status, judge_status, run_checks
from scripts.story_eval.metrics import (
    attitude_metrics,
    behavior_metrics,
    failure_events,
    failure_timeline,
    generation_metrics,
    intent_metrics,
    observed_conditions,
    puruma_signals,
)
from scripts.story_eval.plan import PROJECTS

TOTAL = "total"  # 작품 합계 키
# 두 서버를 같은 조건으로 띄웠는지 리포트 맨 위에 적는 환경변수(비밀값 제외)
SERVER_ENV_KEYS = (
    "LLM_PROVIDER",
    "GEMINI_CHAT_MODEL",
    "GEMINI_THINKING_LEVEL",
    "STORY_GENERATION_ATTEMPTS",
    "GEMINI_HTTP_ATTEMPTS",
    "LLM_TIMEOUT_SECONDS",
    "FRIDGE_QWEN_DIALOGUE_ENABLED",
    "LLM_PROBE_ON_STARTUP",
    "SEED_ON_STARTUP",
    "GEMINI_BASE_URL",
)

REPORT_FORMAT = "mingle-story-eval/1"
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = BACKEND_DIR / "eval_reports"
CONFIG_LABELS = (
    ("thinking_level", "생각 수준(GEMINI_THINKING_LEVEL)"),
    ("story_generation_attempts", "생성 시도 상한(STORY_GENERATION_ATTEMPTS)"),
    ("http_attempts", "HTTP 재시도(GEMINI_HTTP_ATTEMPTS)"),
    ("response_schema", "응답 스키마(STORY_RESPONSE_SCHEMA)"),
    ("temperature", "temperature(LLM_TEMPERATURE)"),
    ("max_tokens", "max_tokens(LLM_MAX_TOKENS)"),
    ("fridge_qwen_dialogue_enabled", "냉장고 Qwen 하이브리드(FRIDGE_QWEN_DIALOGUE_ENABLED)"),
)


# --------------------------------------------------------------------------- #
# 행동 결과
# --------------------------------------------------------------------------- #
def behavior_results(cases: list, observations: list) -> tuple[list[dict], list[dict]]:
    """(결과: 대사 없음, 검토 항목: 대사 포함)."""
    by_id = {case.id: case for case in cases}
    results: list[dict] = []
    review: list[dict] = []
    for case in cases:
        if not case.runnable:
            results.append(
                {"id": case.id, "project": case.project, "origin": case.origin, "category": case.category, "tags": case.tags,
                 "status": "not_run", "reason": case.reason, "auto": [], "manual": False, "expected_behavior": case.expected_behavior}
            )
    for item in observations:
        for case_id in item.case_ids:
            case = by_id[case_id]
            outcome = run_checks(item.observation, case.auto_checks)
            checks = [c.as_dict() for c in outcome]
            status = case_status(item.observation, outcome, case.manual)
            base = {
                "id": case.id,
                "project": case.project,
                "repeat": item.repeat,
                "conversation": item.conversation_index,
                "turn": case.turn,
                "origin": case.origin,
                "category": case.category,
                "tags": case.tags,
                "status": status,
                "auto": checks,
                "manual": case.manual,
                "judge": judge_status(case.judge),
                "provider": item.observation.provider,
                "status_code": item.observation.status_code,
                "safety_notice": item.observation.safety_notice,
                "intent_id": item.observation.intent_id,
                "violations_before_final": ((item.meta or {}).get("generation") or {}).get("violations") or [],
                "attempts": (item.meta or {}).get("attempts"),
                "expected_behavior": case.expected_behavior,
            }
            results.append(base)
            review.append(
                {
                    **base,
                    "situation": case.situation,
                    "review_note": case.review_note,
                    "input_kind": item.input_kind,
                    "input": item.input_text,
                    "replies": [{"speaker": s, "text": t} for s, t in item.observation.replies],
                    "fixed_lines_appended": item.observation.fixed_lines_appended,
                }
            )
    results.sort(key=lambda r: (r["project"], r.get("repeat", 0), r["id"]))
    review.sort(key=lambda r: (r["project"], r["repeat"], r["id"]))
    return results, review


# --------------------------------------------------------------------------- #
# 리포트 조립
# --------------------------------------------------------------------------- #
def build_report(
    *, run: dict, server: dict, assumed: dict, budget: dict, plan_estimate: dict, records: list[dict], behavior: list[dict],
    server_env: dict | None = None, intent_excluded: list[dict] | None = None, http_log: dict | None = None,
) -> dict:
    metrics: dict = {"quality": {}, "intent": {}, "attitude": {}, "behavior": {}, "all_suites": {}, "puruma_signals": {}}
    for project in PROJECTS:
        rows = [r for r in records if r["project"] == project]
        if not rows:
            continue
        quality = [r for r in rows if r["suite"] == "quality"]
        if quality:
            metrics["quality"][project] = generation_metrics(quality)
        intent = [r for r in rows if r["suite"] == "intent"]
        if intent and any(r.get("expected_intent") for r in intent):
            metrics["intent"][project] = intent_metrics(intent)
        if any(r.get("expected_attitude") or r.get("expected_safety") for r in intent):
            metrics["attitude"][project] = attitude_metrics(intent)
        if project == "puruma" and quality:
            metrics["puruma_signals"]["quality"] = puruma_signals(quality)
        b = [r for r in behavior if r["project"] == project]
        if b:
            metrics["behavior"][project] = behavior_metrics(b)
        metrics["all_suites"][project] = generation_metrics(rows)
    # 작품 합계(표본을 합쳐 다시 계산한다. 작품별 비율의 평균이 아니다)
    if len(metrics["all_suites"]) > 1:
        quality = [r for r in records if r["suite"] == "quality"]
        intent = [r for r in records if r["suite"] == "intent" and r.get("expected_intent")]
        if quality:
            metrics["quality"][TOTAL] = generation_metrics(quality)
        if intent:
            metrics["intent"][TOTAL] = intent_metrics(intent)
        if behavior:
            metrics["behavior"][TOTAL] = behavior_metrics(behavior)
        metrics["all_suites"][TOTAL] = generation_metrics(records)
    observed = observed_conditions(records)
    warnings = condition_warnings(server, assumed, observed, records)
    return {
        "format": REPORT_FORMAT,
        "run": run,
        "conditions": {"server": server, "server_env": server_env or {}, "observed": observed, "assumed": assumed, "warnings": warnings},
        "budget": budget,
        "plan": plan_estimate,
        "metrics": metrics,
        "intent_excluded": intent_excluded or [],
        "failures": {"events": failure_events(records), "timeline": failure_timeline(records), "http_log": http_log},
        "behavior": behavior,
        "turns": records,
    }


def condition_warnings(server: dict, assumed: dict, observed: dict, records: list[dict]) -> list[str]:
    warnings = []
    if server.get("provider") == "mock" or any(r.get("provider") == "mock" for r in records):
        warnings.append("Mock 공급자 실행: 생성·의도 분류를 하지 않아 통과율·정확도·토큰은 측정값이 아닙니다(파이프라인 확인용).")
    if server.get("degraded"):
        warnings.append("서버가 시작 점검 실패로 Mock으로 전환된 상태(degraded)였습니다.")
    for key, label in (("story_generation_attempts", "생성 시도"), ("http_attempts", "HTTP 재시도"), ("fridge_qwen_dialogue_enabled", "Qwen")):
        seen = observed.get(key)
        want = assumed.get(key)
        if seen is not None and want is not None and not isinstance(seen, list) and seen != want:
            warnings.append(f"호출 수 계산에 쓴 {label} 값({want})이 서버 기록({seen})과 다릅니다. 예상 호출 수·상한 계산이 맞지 않을 수 있습니다.")
    for key, _ in CONFIG_LABELS:
        if isinstance(observed.get(key), list):
            warnings.append(f"실행 중 서버 설정 {key}가 바뀌었습니다: {observed[key]}")
    if any(r.get("meta") is None and r.get("kind") in ("choice", "free") and r.get("status_code") == 200 and not r.get("safety_notice") for r in records):
        warnings.append("일부 턴의 DB 메타데이터가 없습니다(--no-db 또는 조회 실패). 시도·위반·의도·토큰 집계에서 빠졌습니다.")
    return warnings


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def pct(value) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def num(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in row) + " |" for row in rows]
    return out


def _cond_value(value) -> str:
    if isinstance(value, list):
        return " / ".join(str(v) for v in value) + " (변경됨)"
    if value is None or value == "":
        return "기본값/미지정"
    return str(value)


def conditions_rows(report: dict) -> list[list]:
    run, cond = report["run"], report["conditions"]
    server, observed = cond["server"], cond["observed"]
    rows = [
        ["실행 시각", f"{run['started_at']} ~ {run.get('finished_at') or '-'}"],
        ["라벨", run["label"]],
        ["서버 공급자 / 모델(health)", f"{server.get('provider')} / {server.get('chat_model')}"],
        ["응답에 기록된 모델", ", ".join(observed.get("models") or []) or "N/A"],
    ]
    rows += [[label, _cond_value(observed.get(key))] for key, label in CONFIG_LABELS]
    rows += [
        ["Qwen 시도 관측", "있음" if observed.get("qwen_attempted_any") else "없음"],
        ["스위트 / 작품", f"{', '.join(run['suites'])} / {', '.join(run['projects'])}"],
        ["반복 횟수", run["repeat"]],
        ["장면 세트", run["scene_set"]],
        ["상태", run["status"] + (f" ({run['stop_reason']})" if run.get("stop_reason") else "")],
        ["호출(상한 기준) / 상한", f"{report['budget']['used_upper_bound']} / {report['budget']['max_calls'] or '없음'}"],
        ["예상 호출(최소~최대)", f"{report['plan']['total_min_calls']} ~ {report['plan']['total_max_calls']}"],
    ]
    return rows


def render_summary(report: dict) -> str:
    out = [f"# 스토리 채팅 평가 리포트 · {report['run']['label']}", ""]
    env = report["conditions"].get("server_env") or {}
    if env:
        out += ["## 서버 설정(실행기가 띄운 서버의 환경변수, 비밀값 제외)", ""]
        out += _table(["환경변수", "값"], [[k, env.get(k, "(.env/기본값)")] for k in SERVER_ENV_KEYS if k in env])
        out += [""]
    out += ["## 실행 조건", ""]
    out += _table(["항목", "값"], conditions_rows(report))
    out += ["", "서버 설정 값은 각 턴의 응답 메시지 기록(extra.generation.config)에서 읽었습니다. 비밀값은 기록하지 않습니다."]
    if report["conditions"]["warnings"]:
        out += ["", "**주의**", ""] + [f"- {w}" for w in report["conditions"]["warnings"]]
    metrics = report["metrics"]

    out += ["", "## 1. 10턴 진행 품질", ""]
    if metrics["quality"]:
        rows = []
        for project, m in metrics["quality"].items():
            t = m["tokens"]
            rows.append([
                project, m["llm_turns"], m["generated_turns"], pct(m["first_pass_rate"]), pct(m["pass_after_correction_rate"]),
                pct(m["fallback_rate"]), m["http_errors"], num(m["latency_ms"]["p50"]), num(m["latency_ms"]["p95"]),
                num(m["wall_ms"]["p50"]), num(m["wall_ms"]["p95"]),
                f"{num(t['prompt_tokens'])} / {num(t['completion_tokens'])} / {num(t['thinking_tokens'])}",
            ])
        out += _table(["작품", "LLM 턴", "생성 턴", "첫 시도 통과", "교정 후 통과", "대체 응답", "HTTP 오류", "지연 p50", "지연 p95", "왕복 p50", "왕복 p95", "토큰 입력/출력/생각"], rows)
        out += ["", "- 통과율 분모는 생성 턴(Mock 제외 LLM 턴)입니다. 교정 후 통과는 첫 시도 통과를 포함한 누적값입니다.",
                "- 지연은 서버가 기록한 생성 지연(AI 응답 턴, ms), 왕복은 실행기에서 잰 HTTP 왕복(ms)입니다."]
        for project, m in metrics["quality"].items():
            if project == TOTAL:
                continue
            if m["fallback_reasons"]:
                out += ["", f"**{project} 대체 사유**", ""] + _table(["사유", "턴 수"], [[k, v] for k, v in m["fallback_reasons"].items()])
            if m["violations_by_scene"]:
                out += ["", f"**{project} 장면별 응답 제어 위반(모든 시도)**", ""]
                out += _table(["턴", "위반 코드(횟수)"], [[t, ", ".join(f"{k} {v}" for k, v in c.items())] for t, c in m["violations_by_scene"].items()])
            if m["qwen"]["attempted"]:
                q = m["qwen"]
                out += ["", f"**{project} Qwen 하이브리드**: 시도 {q['attempted']}, 사용 {q['used']} ({pct(q['used_rate'])}), 지연 p50 {num(q['latency_p50'])} / p95 {num(q['latency_p95'])} ms, 미사용 사유 {q['fallback_reasons'] or '-'}"]
    else:
        out += ["실행하지 않았습니다."]

    signals = metrics.get("puruma_signals", {}).get("quality")
    if signals:
        out += ["", "**puruma 진행 신호(10턴 품질 스위트)**", ""]
        out += _table(["항목", "값"], [
            ["대화 수", signals["conversations"]],
            ["홍보 R1 / R2 / R3 노출 턴", " / ".join(str(signals["promo_by_rule"][k]) for k in ("R1", "R2", "R3"))],
            ["홍보 ID별", ", ".join(f"{k} {v}" for k, v in signals["promo_by_id"].items()) or "-"],
            ["CC 분기 선택 턴 / 덧붙임 대사", f"{signals['cc_branch_turns']} / {signals['cc_line_appended']}"],
            ["10턴 진로", ", ".join(f"{k} {v}" for k, v in signals["final_paths"].items()) or "-"],
            ["엔딩", ", ".join(f"{k} {v}" for k, v in signals["endings"].items()) or "-"],
            ["감정 코드", ", ".join(f"{k} {v}" for k, v in signals["emotion_codes"].items()) or "-"],
        ])

    out += ["", "## 2. 자유 입력 의도 분류", ""]
    if metrics["intent"]:
        rows = [[p, m["samples"], m["correct"], pct(m["accuracy"]), m["answered"], pct(m["accuracy_answered"]), m["no_prediction"], m["fallback"], m["http_errors"], m["mock"]] for p, m in metrics["intent"].items()]
        out += _table(["작품", "표본", "정답", "정확도", "분류 응답", "정확도(분류 응답 기준)", "분류 없음", "대체 응답", "HTTP 오류", "Mock(제외)"], rows)
        out += ["", "정답 세트: 냉장고·구름섬은 data/*_data/scenario/*_scene_cards_draft.json의 intents[].free_input_examples(결말 판정 story_judgement.py가 이 분류를 씁니다). 푸르마는 data/tests/pruma_topic_classification_tests.json을 cases/puruma_intent_map.json으로 topic_*에 매핑했습니다(스탯 계산 puruma_state.py가 씁니다)."]
        if report.get("intent_excluded"):
            out += ["", f"매핑할 수 없어 제외한 정답 세트 {len(report['intent_excluded'])}건: " + ", ".join(f"{e['id']}({e['reason']})" for e in report["intent_excluded"])]
        for project, m in metrics["intent"].items():
            if project == TOTAL:
                continue
            out += ["", f"**{project} 장면별 정확도**", ""]
            out += _table(["턴", "표본", "정답", "정확도"], [[t, s["samples"], s["correct"], pct(s["accuracy"])] for t, s in m["by_turn"].items()])
            if m["confusions"]:
                out += ["", f"**{project} 혼동 사례 ({len(m['confusions'])}건)**", ""]
                out += _table(["턴", "입력(정답 세트 예시)", "정답", "예측", "공급자"], [[c["turn"], c["input"], c["expected"], c["predicted"] or "(없음)", c["provider"] or c["status_code"]] for c in m["confusions"]])
    else:
        out += ["실행하지 않았습니다."]

    if metrics.get("attitude"):
        out += ["", "## 2-1. 푸르마 태도(attitude) 분류", ""]
        rows = [[p, m["samples"], m["correct"], pct(m["accuracy"]), pct(m["accuracy_answered"]), m["fallback"], m["http_errors"], m["mock"], f"{m['override_safety_notice']} / {m['override_cases']}"] for p, m in metrics["attitude"].items()]
        out += _table(["작품", "표본", "정답", "정확도", "정확도(분류 응답 기준)", "대체 응답", "HTTP 오류", "Mock(제외)", "위기 우선 케이스 안내"], rows)
        out += ["", "정답 세트: data/tests/pruma_attitude_classification_tests.json(cases). override_cases(위기 표현 포함)는 태도를 채점하지 않고 safety_notice만 확인합니다."]
        for project, m in metrics["attitude"].items():
            labels = sorted({k for row in m["confusion"].values() for k in row} | set(m["confusion"]))
            if m["confusion"]:
                out += ["", f"**{project} 혼동 행렬(행=정답, 열=예측)**", ""]
                out += _table(["정답 \\ 예측", *labels], [[k, *[row.get(l, 0) for l in labels]] for k, row in m["confusion"].items()])
            if m["confusions"]:
                out += ["", f"**{project} 오분류 ({len(m['confusions'])}건)**", ""]
                out += _table(["턴", "id", "입력(정답 세트)", "정답", "예측", "공급자"], [[c["turn"], c["id"], c["input"], c["expected"], c["predicted"] or "(없음)", c["provider"]] for c in m["confusions"]])

    out += ["", "## 3. 행동 테스트", ""]
    if report["behavior"]:
        rows = [[p, m["cases"], m["statuses"].get("pass", 0), m["statuses"].get("needs_review", 0), m["statuses"].get("fail", 0), m["statuses"].get("inconclusive", 0), m["statuses"].get("error", 0), m["statuses"].get("not_run", 0)] for p, m in metrics["behavior"].items()]
        out += _table(["작품", "케이스", "통과", "자동 통과·사람 검토", "실패", "판정 불가", "오류", "미실행"], rows)
        out += ["", "상태: 통과=자동 검사만 있고 모두 통과 · 자동 통과·사람 검토=review.md에서 의미를 판단 · 실패=자동 검사 실패 · 판정 불가=AI 대신 고정 대사(대체 응답·Mock)."]
        rows = []
        for r in report["behavior"]:
            auto = "; ".join(f"{'✓' if c['passed'] else '✗'} {c['type']}{(' (' + c['detail'] + ')') if c['detail'] and not c['passed'] else ''}" for c in r["auto"]) or "-"
            rows.append([r["project"], r["id"], r.get("turn") or "-", r.get("repeat", "-"), r["status"], auto, "필요" if r["manual"] else "-", r.get("reason", "")])
        out += [""] + _table(["작품", "케이스", "턴", "반복", "상태", "자동 검사", "사람 검토", "비고"], rows)
    else:
        out += ["실행하지 않았습니다."]

    out += ["", "## 비용(모든 스위트)", ""]
    rows = []
    for project, m in metrics["all_suites"].items():
        t = m["tokens"]
        rows.append([project, m["llm_turns"], t["generation_calls"], num(t["prompt_tokens"]), num(t["completion_tokens"]), num(t["thinking_tokens"]), m["qwen"]["attempted"]])
    out += _table(["작품", "LLM 턴", "생성 호출", "입력 토큰", "출력 토큰", "생각 토큰", "Qwen 호출"], rows)
    b = report["budget"]
    out += ["", f"상한 기준 사용량 {b['used_upper_bound']} (생성 호출 {b['generation_calls']} × HTTP 재시도 상한 + Qwen {b['qwen_calls']}). {b['note']}"]
    out += render_failures(report)
    return "\n".join(out) + "\n"


FAILURE_NOTE = "실패 분류: provider_http_503 등은 AI 실패로 고정 대사(provider=fallback)가 나간 사유 코드, http_NNN은 스토리 API 자체 오류입니다. 시각은 요청을 보낸 시각(KST)입니다."


def render_failures(report: dict) -> list[str]:
    failures = report.get("failures") or {}
    events = failures.get("events") or []
    out = ["", "## 공급자 실패 시각(KST)", ""]
    http_log = failures.get("http_log")
    if http_log:
        out += ["### Gemini HTTP 시도(서버 로그 기준, 재시도로 회복된 실패 포함)", ""]
        out += [f"generateContent HTTP 요청 {http_log['requests']}회(그중 재시도 {http_log['retries']}회) · 상태별: " + (", ".join(f"{k} {v}" for k, v in http_log["by_status"].items()) or "-"), ""]
        codes = sorted({k for b in http_log["buckets"].values() for k in b if k != "requests"})
        out += _table(["시간대", "요청", *codes], [[t, b.get("requests", 0), *[b.get(c, 0) for c in codes]] for t, b in http_log["buckets"].items()])
        if http_log["non_200"]:
            out += ["", f"200이 아닌 HTTP 시도 {len(http_log['non_200'])}건", ""]
            out += _table(["시각", "시도", "상태"], [[e["at"], e["attempt"], e["status"]] for e in http_log["non_200"]])
        out += ["", "### 턴 단위 실패(재시도까지 실패해 고정 대사가 나간 턴)", ""]
    if not events:
        return out + ["실패(대체 응답·HTTP 오류) 없음."]
    timeline = failures["timeline"]
    kinds = sorted({k for b in timeline["buckets"].values() for k in b if k != "llm_turns"})
    out += [f"{timeline['minutes']}분 단위 LLM 턴 수와 실패 수", ""]
    out += _table(["시간대", "LLM 턴", *kinds], [[t, b.get("llm_turns", 0), *[b.get(k, 0) for k in kinds]] for t, b in timeline["buckets"].items()])
    out += ["", f"실패 턴 {len(events)}건", ""]
    out += _table(["시각", "스위트", "작품", "턴", "분류", "생성 호출"], [[e["at"], e["suite"], e["project"], e["turn"], e["kind"], num(e["generation_calls"])] for e in events])
    return out + ["", FAILURE_NOTE]


def render_review(report: dict, review: list[dict]) -> str:
    out = [
        f"# 행동 테스트 사람 검토 · {report['run']['label']}",
        "",
        "이 파일에는 입력과 응답 원문이 있습니다. 로컬 검토용이며 저장소·공유 채널에 올리지 않습니다.",
        f"실행: {report['run']['started_at']} · 모델: {', '.join(report['conditions']['observed'].get('models') or []) or 'N/A'}",
        "",
    ]
    for item in review:
        out += [f"## {item['project']} · {item['id']} (턴 {item['turn']}, 반복 {item['repeat']})", ""]
        if item.get("category") or item.get("situation"):
            out += [f"- 범주: {item.get('category') or '-'} · 원본 상황: {item.get('situation') or '-'}"]
        out += [f"- 기대 동작: {item['expected_behavior'] or '-'}"]
        if item.get("review_note"):
            out += [f"- 검토 메모: {item['review_note']}"]
        out += [f"- 상태: {item['status']} · 공급자: {item['provider']} · 시도: {item['attempts']} · 교정 전 위반: {', '.join(item['violations_before_final']) or '-'} · 의도: {item['intent_id'] or '-'}"]
        out += [f"- 입력({item['input_kind']}): {item['input'] if item['input'] is not None else '(입력 없음)'}", "- 응답:"]
        for i, line in enumerate(item["replies"]):
            fixed = " (장면 고정 대사)" if item["provider"] != "fixed" and i >= len(item["replies"]) - item["fixed_lines_appended"] else ""
            out += [f"  - **{line['speaker']}**{fixed}: {line['text']}"]
        if item["auto"]:
            out += ["- 자동 검사: " + "; ".join(f"{'✓' if c['passed'] else '✗'} {c['type']} {c['detail']}".strip() for c in item["auto"])]
        if item["manual"]:
            out += ["- 사람 판정: [ ] 기대 동작 충족  [ ] 미충족 · 근거:"]
        out += [""]
    return "\n".join(out) + "\n"


def finalize_run(
    *, label: str, base_url: str, suites: list[str], projects: list[str], repeat: int, quality_repeat: int | None,
    started, finished, status: str, stop_reason: str | None, state, cases: list, server: dict, assumed: dict,
    budget: dict, estimate: dict, db_metadata: bool, out_dir: Path, server_env: dict | None = None, http_log: dict | None = None,
) -> tuple[dict, dict[str, Path]]:
    """한 실행(모델 하나)의 상태를 리포트로 묶어 out_dir에 쓴다. run 명령과 ab 명령이 같이 쓴다."""
    from scripts.story_eval.plan import SCENE_SETS, puruma_samples

    if state.aborted_conversations and status == "completed":
        status = "completed_with_errors"
    behavior, review = behavior_results(list(cases), state.behavior)
    excluded = puruma_samples()[1] if "intent" in suites and "puruma" in projects else []
    run = {
        "label": label,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "base_url": base_url,
        "suites": suites,
        "projects": projects,
        "repeat": repeat,
        "quality_repeat": quality_repeat,
        "scene_set": ", ".join(sorted({SCENE_SETS[p] for p in projects})),
        "status": status,
        "stop_reason": stop_reason,
        "skipped_steps": state.skipped_steps,
        "aborted_conversations": state.aborted_conversations,
        "db_metadata": db_metadata,
    }
    report = build_report(run=run, server=server, assumed=assumed, budget=budget, plan_estimate=estimate, records=state.records,
                          behavior=behavior, server_env=server_env, intent_excluded=excluded, http_log=http_log)
    return report, write_run(report, review, out_dir)


def write_run(report: dict, review: list[dict], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": out_dir / "report.json",
        "summary": out_dir / "summary.md",
        "review_md": out_dir / "review.md",
        "review_json": out_dir / "review.json",
    }
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["summary"].write_text(render_summary(report), encoding="utf-8")
    paths["review_json"].write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["review_md"].write_text(render_review(report, review), encoding="utf-8")
    return paths


# --------------------------------------------------------------------------- #
# 비교
# --------------------------------------------------------------------------- #
def load_report(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != REPORT_FORMAT:
        raise ValueError(f"{path}: 평가 리포트 형식이 아닙니다({data.get('format')}).")
    return data


def _get(data: dict, *keys):
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _counts_rows(reports: list[dict], prefix: str, path: tuple, fmt=None) -> list[list]:
    """{코드: 개수} 지표를 코드별 행으로 펼친다."""
    keys: list[str] = []
    for r in reports:
        for key in (_get(r["metrics"], *path) or {}):
            if key not in keys:
                keys.append(key)
    return [[f"{prefix} {key}"] + [num((_get(r["metrics"], *path) or {}).get(key, 0)) for r in reports] for key in sorted(keys)]


def render_compare(reports: list[dict]) -> str:
    labels = [r["run"]["label"] for r in reports]
    out = ["# 스토리 채팅 평가 비교", ""]
    envs = [r["conditions"].get("server_env") or {} for r in reports]
    if any(envs):
        out += ["## 서버 설정(환경변수, 비밀값 제외)", ""]
        rows = [[key] + [env.get(key, "-") for env in envs] for key in SERVER_ENV_KEYS if any(key in env for env in envs)]
        out += _table(["환경변수", *labels], rows)
        diff = [row[0] for row in rows if row[0] != "GEMINI_CHAT_MODEL" and len(set(row[1:])) > 1]
        out += ["", f"**주의: 모델 외 설정이 다릅니다: {', '.join(diff)}**" if diff else "모델(GEMINI_CHAT_MODEL) 외 설정은 모두 같습니다.", ""]
    out += ["## 실행 조건", ""]
    cond_rows = []
    keys = [("실행 시각", lambda r: f"{r['run']['started_at']} ~ {r['run'].get('finished_at') or '-'}"), ("서버 모델(health)", lambda r: r["conditions"]["server"].get("chat_model")),
            ("응답 모델", lambda r: ", ".join(r["conditions"]["observed"].get("models") or []) or "N/A")]
    keys += [(label, (lambda k: lambda r: _cond_value(r["conditions"]["observed"].get(k)))(key)) for key, label in CONFIG_LABELS]
    keys += [("반복(품질 / 그 외)", lambda r: f"{r['plan']['assumptions'].get('quality_repeat') or r['run']['repeat']} / {r['run']['repeat']}"),
             ("스위트", lambda r: ", ".join(r["run"]["suites"])), ("작품", lambda r: ", ".join(r["run"]["projects"])),
             ("상태", lambda r: r["run"]["status"] + (f" ({r['run']['stop_reason']})" if r["run"].get("stop_reason") else "")),
             ("호출(상한 기준) / 상한", lambda r: f"{r['budget']['used_upper_bound']} / {r['budget']['max_calls'] or '없음'}")]
    for name, fn in keys:
        cond_rows.append([name] + [fn(r) for r in reports])
    out += _table(["항목", *labels], cond_rows)
    logs = [_get(r, "failures", "http_log") for r in reports]
    if any(logs):
        out += ["", "## Gemini HTTP 시도 요약(서버 로그)", ""]
        statuses = sorted({k for l in logs if l for k in l["by_status"]})
        rows = [["HTTP 요청 수"] + [num(l["requests"]) if l else "N/A" for l in logs], ["재시도 수"] + [num(l["retries"]) if l else "N/A" for l in logs]]
        rows += [[f"상태 {code}"] + [num((l or {}).get("by_status", {}).get(code, 0)) if l else "N/A" for l in logs] for code in statuses]
        out += _table(["항목", *labels], rows)

    def metric_rows(project: str) -> list[list]:
        spec = [
            ("품질 · LLM 턴", ("quality", project, "llm_turns"), num),
            ("품질 · 생성 턴(분모)", ("quality", project, "generated_turns"), num),
            ("품질 · 첫 시도 통과율", ("quality", project, "first_pass_rate"), pct),
            ("품질 · 교정 후 통과율", ("quality", project, "pass_after_correction_rate"), pct),
            ("품질 · 대체 응답 비율", ("quality", project, "fallback_rate"), pct),
            ("품질 · HTTP 오류", ("quality", project, "http_errors"), num),
            ("품질 · 지연 p50 (ms)", ("quality", project, "latency_ms", "p50"), num),
            ("품질 · 지연 p95 (ms)", ("quality", project, "latency_ms", "p95"), num),
            ("품질 · 왕복 p50 (ms)", ("quality", project, "wall_ms", "p50"), num),
            ("품질 · 왕복 p95 (ms)", ("quality", project, "wall_ms", "p95"), num),
            ("품질 · Qwen 사용률", ("quality", project, "qwen", "used_rate"), pct),
            ("전 스위트 · 대체 응답 비율", ("all_suites", project, "fallback_rate"), pct),
            ("전 스위트 · 첫 시도 통과율", ("all_suites", project, "first_pass_rate"), pct),
            ("전 스위트 · 교정 후 통과율", ("all_suites", project, "pass_after_correction_rate"), pct),
            ("전 스위트 · 지연 p50 (ms)", ("all_suites", project, "latency_ms", "p50"), num),
            ("전 스위트 · 지연 p95 (ms)", ("all_suites", project, "latency_ms", "p95"), num),
            ("의도 · 표본", ("intent", project, "samples"), num),
            ("의도 · 정확도", ("intent", project, "accuracy"), pct),
            ("의도 · 정확도(분류 응답 기준)", ("intent", project, "accuracy_answered"), pct),
            ("태도 · 표본", ("attitude", project, "samples"), num),
            ("태도 · 정확도", ("attitude", project, "accuracy"), pct),
            ("태도 · 위기 우선 케이스 안내", ("attitude", project, "override_safety_notice"), num),
            ("행동 · 케이스", ("behavior", project, "cases"), num),
            ("행동 · 자동 검사 전부 통과율", ("behavior", project, "auto_pass_rate"), pct),
            ("행동 · 통과", ("behavior", project, "statuses", "pass"), num),
            ("행동 · 자동 통과·사람 검토", ("behavior", project, "statuses", "needs_review"), num),
            ("행동 · 실패", ("behavior", project, "statuses", "fail"), num),
            ("행동 · 판정 불가(대체 응답)", ("behavior", project, "statuses", "inconclusive"), num),
            ("행동 · 오류", ("behavior", project, "statuses", "error"), num),
            ("전체 · 입력 토큰", ("all_suites", project, "tokens", "prompt_tokens"), num),
            ("전체 · 출력 토큰", ("all_suites", project, "tokens", "completion_tokens"), num),
            ("전체 · 생각 토큰", ("all_suites", project, "tokens", "thinking_tokens"), num),
            ("전체 · 생성 호출", ("all_suites", project, "tokens", "generation_calls"), num),
        ]
        rows = []
        for name, path, fmt in spec:
            values = [_get(r["metrics"], *path) for r in reports]
            if all(v is None for v in values):
                continue
            rows.append([name] + [fmt(v) if v is not None else ("0" if "행동 ·" in name and _get(r["metrics"], "behavior", project) else "N/A") for v, r in zip(values, reports)])
        rows += _counts_rows(reports, "전 스위트 · 대체 사유", ("all_suites", project, "fallback_reasons"))
        rows += _counts_rows(reports, "품질 · 위반", ("quality", project, "violations_total"))
        return rows

    for project in (*PROJECTS, TOTAL):
        rows = metric_rows(project)
        if rows:
            title = "합계(세 작품 표본 합산)" if project == TOTAL else project
            out += ["", f"## {title}", ""] + _table(["지표", *labels], rows)

    signals = [_get(r["metrics"], "puruma_signals", "quality") for r in reports]
    if any(signals):
        out += ["", "## puruma 진행 신호(품질 스위트)", ""]
        sig_rows = [
            ["홍보 R1 / R2 / R3"] + [" / ".join(str((s or {}).get("promo_by_rule", {}).get(k, 0)) for k in ("R1", "R2", "R3")) if s else "N/A" for s in signals],
            ["CC 분기 선택 / 덧붙임"] + [f"{s['cc_branch_turns']} / {s['cc_line_appended']}" if s else "N/A" for s in signals],
            ["10턴 진로"] + [", ".join(f"{k} {v}" for k, v in s["final_paths"].items()) if s else "N/A" for s in signals],
            ["엔딩"] + [", ".join(f"{k} {v}" for k, v in s["endings"].items()) if s else "N/A" for s in signals],
        ]
        out += _table(["항목", *labels], sig_rows)

    # 시간대별 실패: 두 실행을 같은 10분 칸에 맞춰 나란히 본다(번갈아 실행했다면 같은 시간대를 공유한다).
    http_buckets = [((_get(r, "failures", "http_log") or {}).get("buckets") or {}) for r in reports]
    hb = sorted({b for t in http_buckets for b in t})
    if any(any(k != "requests" for v in t.values() for k in v) for t in http_buckets):
        out += ["", "## 시간대별 Gemini HTTP 실패(KST, 10분 단위, 실패 / 요청, 서버 로그)", ""]
        rows = []
        for bucket in hb:
            row = [bucket]
            for t in http_buckets:
                b = t.get(bucket) or {}
                fails = {k: v for k, v in b.items() if k != "requests"}
                row.append(f"{sum(fails.values())} / {b.get('requests', 0)}" + (f" ({', '.join(f'{k} {v}' for k, v in sorted(fails.items()))})" if fails else ""))
            rows.append(row)
        out += _table(["시간대", *labels], rows)
    timelines = [(_get(r, "failures", "timeline", "buckets") or {}) for r in reports]
    buckets = sorted({b for t in timelines for b in t})
    if buckets and any(e for r in reports for e in (_get(r, "failures", "events") or [])):
        out += ["", "## 시간대별 턴 실패(KST, 10분 단위, 고정 대사로 넘어간 턴 / LLM 턴)", ""]
        rows = []
        for bucket in buckets:
            row = [bucket]
            for t in timelines:
                b = t.get(bucket) or {}
                fails = {k: v for k, v in b.items() if k != "llm_turns"}
                row.append(f"{sum(fails.values())} / {b.get('llm_turns', 0)}" + (f" ({', '.join(f'{k} {v}' for k, v in sorted(fails.items()))})" if fails else ""))
            rows.append(row)
        out += _table(["시간대", *labels], rows)
        out += ["", FAILURE_NOTE]

    failed = [(r["run"]["label"], b["project"], b["id"], "; ".join(c["type"] for c in b["auto"] if not c["passed"])) for r in reports for b in r["behavior"] if b["status"] == "fail"]
    if failed:
        out += ["", "## 자동 검사 실패 케이스", ""] + _table(["실행", "작품", "케이스", "실패 검사"], [list(f) for f in failed])
    warn = [(r["run"]["label"], w) for r in reports for w in r["conditions"]["warnings"]]
    if warn:
        out += ["", "## 주의", ""] + [f"- {label}: {w}" for label, w in warn]
    out += ["", "같은 입력·적은 반복의 비교는 표본이 작습니다. 차이가 작으면 반복 횟수를 늘려 다시 확인하세요."]
    return "\n".join(out) + "\n"
