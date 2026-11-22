"""턴 기록(대사 원문 없음) → 집계 지표. 순수 함수만 둔다(테스트 대상).

턴 기록의 주요 키
    suite, project, turn(1부터), kind(choice|free|fixed|crisis), status_code, provider, model,
    latency_ms(서버가 기록한 생성 지연), wall_ms(실행기 왕복), safety_notice,
    expected_intent, example(의도 스위트의 정답 예시 문장: 데이터 파일 문장),
    meta: DB에서 읽은 메타데이터 또는 None
        attempts, intent_id, fallback_reason, fixed_lines_appended,
        generation{calls, violations, prompt_tokens, completion_tokens, thinking_tokens, config},
        dialogue{qwen_attempted, qwen_used, qwen_latency_ms, fallback_reason}
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

LLM_KINDS = ("choice", "free")
NON_AI_PROVIDERS = ("fallback", "fixed", "safety", "mock")


def percentile(values: list[float], q: float) -> float | None:
    """nearest-rank 백분위수. 값이 없으면 None."""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    rank = max(1, math.ceil(q / 100 * len(data)))
    return data[rank - 1]


def ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _gen(record: dict) -> dict:
    return ((record.get("meta") or {}).get("generation")) or {}


def llm_turns(records: list[dict]) -> list[dict]:
    """LLM 생성을 요청한 턴(선택지·자유 입력). 위기 안내 턴은 서버가 LLM을 부르지 않으므로 뺀다."""
    return [r for r in records if r.get("kind") in LLM_KINDS and not r.get("safety_notice")]


def generation_metrics(records: list[dict]) -> dict:
    turns = llm_turns(records)
    ok = [r for r in turns if r.get("status_code") == 200]
    errors = [r for r in turns if r.get("status_code") != 200]
    # Mock 공급자는 생성 자체를 하지 않아 통과율을 잴 수 없다(분모에서 뺀다).
    generated = [r for r in ok if r.get("provider") != "mock"]
    ai = [r for r in generated if r.get("provider") not in NON_AI_PROVIDERS]
    fallback = [r for r in generated if r.get("provider") == "fallback"]
    with_meta = [r for r in ai if r.get("meta")]
    first = [r for r in with_meta if (r["meta"].get("attempts") or 0) == 1]
    corrected = [r for r in with_meta if (r["meta"].get("attempts") or 0) >= 2]

    by_scene: dict[int, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for r in ok:
        for code in _gen(r).get("violations") or []:
            by_scene[r["turn"]][code] += 1
            totals[code] += 1

    latencies = [r.get("latency_ms") for r in ai if isinstance(r.get("latency_ms"), int)]
    walls = [r.get("wall_ms") for r in ok if isinstance(r.get("wall_ms"), (int, float))]
    qwen_attempted = [r for r in ok if ((r.get("meta") or {}).get("dialogue") or {}).get("qwen_attempted")]
    qwen_used = [r for r in qwen_attempted if r["meta"]["dialogue"].get("qwen_used")]
    qwen_lat = [r["meta"]["dialogue"].get("qwen_latency_ms") for r in qwen_attempted]

    return {
        "llm_turns": len(turns),
        "http_errors": len(errors),
        "http_error_codes": dict(Counter(str(r.get("status_code")) for r in errors)),
        "mock_turns": sum(1 for r in ok if r.get("provider") == "mock"),
        "generated_turns": len(generated),
        "meta_missing": len(ai) - len(with_meta),
        "first_pass": len(first),
        "corrected_pass": len(corrected),
        "first_pass_rate": ratio(len(first), len(generated)),
        "pass_after_correction_rate": ratio(len(first) + len(corrected), len(generated)),
        "fallback": len(fallback),
        "fallback_rate": ratio(len(fallback), len(generated)),
        "fallback_reasons": dict(Counter((r.get("meta") or {}).get("fallback_reason") or "unknown" for r in fallback)),
        "violations_total": dict(totals.most_common()),
        "violations_by_scene": {str(t): dict(c.most_common()) for t, c in sorted(by_scene.items())},
        "latency_ms": {
            "n": len(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
        },
        "wall_ms": {"n": len(walls), "p50": percentile(walls, 50), "p95": percentile(walls, 95)},
        "qwen": {
            "attempted": len(qwen_attempted),
            "used": len(qwen_used),
            "used_rate": ratio(len(qwen_used), len(qwen_attempted)),
            "fallback_reasons": dict(Counter(r["meta"]["dialogue"].get("fallback_reason") or "-" for r in qwen_attempted if not r["meta"]["dialogue"].get("qwen_used"))),
            "latency_p50": percentile([v for v in qwen_lat if isinstance(v, int)], 50),
            "latency_p95": percentile([v for v in qwen_lat if isinstance(v, int)], 95),
        },
        "tokens": token_totals(records),
    }


def token_totals(records: list[dict]) -> dict:
    """공급자가 돌려준 토큰 수 합계(교정 재시도·실패 시도 포함). 보고하지 않은 공급자는 None으로 둔다."""
    sums = {"prompt_tokens": None, "completion_tokens": None, "thinking_tokens": None}
    calls = 0
    turns_with_tokens = 0
    for r in records:
        gen = _gen(r)
        calls += gen.get("calls") or 0
        has = False
        for key in sums:
            value = gen.get(key)
            if isinstance(value, int):
                sums[key] = (sums[key] or 0) + value
                has = True
        turns_with_tokens += has
    return {**sums, "generation_calls": calls, "turns_with_tokens": turns_with_tokens}


def intent_metrics(records: list[dict]) -> dict:
    all_samples = [r for r in records if r.get("expected_intent") and r.get("kind") == "free"]
    # Mock 공급자는 분류하지 않으므로 정확도 분모에서 뺀다(개수만 따로 보고).
    samples = [r for r in all_samples if r.get("provider") != "mock"]

    def predicted(r: dict) -> str | None:
        return (r.get("meta") or {}).get("intent_id")

    def summarize(rows: list[dict]) -> dict:
        correct = sum(1 for r in rows if predicted(r) == r["expected_intent"])
        answered = sum(1 for r in rows if predicted(r))
        return {
            "samples": len(rows),
            "answered": answered,
            "correct": correct,
            "accuracy": ratio(correct, len(rows)),
            "accuracy_answered": ratio(correct, answered),
        }

    by_turn = defaultdict(list)
    by_intent = defaultdict(list)
    for r in samples:
        by_turn[r["turn"]].append(r)
        by_intent[r["expected_intent"]].append(r)
    confusions = [
        {
            "turn": r["turn"],
            "input": r.get("example"),
            "expected": r["expected_intent"],
            "predicted": predicted(r),
            "provider": r.get("provider"),
            "status_code": r.get("status_code"),
        }
        for r in samples
        if predicted(r) != r["expected_intent"]
    ]
    return {
        **summarize(samples),
        "no_prediction": sum(1 for r in samples if not predicted(r)),
        "fallback": sum(1 for r in samples if r.get("provider") == "fallback"),
        "mock": sum(1 for r in all_samples if r.get("provider") == "mock"),
        "http_errors": sum(1 for r in samples if r.get("status_code") != 200),
        "by_turn": {str(t): summarize(rows) for t, rows in sorted(by_turn.items())},
        "by_intent": {k: summarize(rows) for k, rows in sorted(by_intent.items())},
        "confusions": confusions,
    }


def behavior_metrics(results: list[dict]) -> dict:
    statuses = Counter(r["status"] for r in results)
    by_tag: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        for tag in r.get("tags") or ["-"]:
            by_tag[tag][r["status"]] += 1
    runnable = [r for r in results if r["status"] != "not_run"]
    # AI가 아닌 응답(판정 불가)·HTTP 오류는 자동 검사 통과율 분모에서 뺀다.
    auto_checked = [r for r in runnable if r.get("auto") and r["status"] not in ("inconclusive", "error")]
    auto_pass = [r for r in auto_checked if all(c["passed"] for c in r["auto"])]
    return {
        "cases": len(results),
        "statuses": dict(statuses),
        "auto_checked": len(auto_checked),
        "auto_all_passed": len(auto_pass),
        "auto_pass_rate": ratio(len(auto_pass), len(auto_checked)),
        "needs_review": statuses.get("needs_review", 0),
        "by_tag": {tag: dict(c) for tag, c in sorted(by_tag.items())},
        "failed_cases": sorted({r["id"] for r in results if r["status"] == "fail"}),
    }


def observed_conditions(records: list[dict]) -> dict:
    """DB에 기록된 서버 실제 설정. 턴마다 다르면 모든 값을 목록으로 남긴다."""
    models = sorted({r.get("model") for r in records if r.get("kind") in LLM_KINDS and r.get("model") and r.get("provider") not in ("fallback", "safety")})
    configs: dict[str, set] = defaultdict(set)
    for r in records:
        for key, value in (_gen(r).get("config") or {}).items():
            configs[key].add(value if not isinstance(value, (list, dict)) else str(value))
    flat = {key: (sorted(values, key=str)[0] if len(values) == 1 else sorted(values, key=str)) for key, values in configs.items()}
    qwen_seen = any(((r.get("meta") or {}).get("dialogue") or {}).get("qwen_attempted") for r in records)
    return {"models": models, **flat, "qwen_attempted_any": qwen_seen}


# --------------------------------------------------------------------------- #
# 푸르마
# --------------------------------------------------------------------------- #
def _attitude(record: dict) -> str | None:
    return (((record.get("meta") or {}).get("puruma")) or {}).get("attitude")


def attitude_metrics(records: list[dict]) -> dict:
    """푸르마 자유 입력 태도 분류 정확도(정답: data/tests/pruma_attitude_classification_tests.json).

    위기 우선(override) 케이스는 태도를 채점하지 않고 safety_notice가 나왔는지만 센다.
    """
    all_samples = [r for r in records if r.get("expected_attitude") and r.get("kind") == "free"]
    samples = [r for r in all_samples if r.get("provider") != "mock"]
    correct = sum(1 for r in samples if _attitude(r) == r["expected_attitude"])
    answered = sum(1 for r in samples if _attitude(r))
    matrix: dict[str, Counter] = defaultdict(Counter)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for r in samples:
        matrix[r["expected_attitude"]][_attitude(r) or "(없음)"] += 1
        by_label[r["expected_attitude"]].append(r)
    override = [r for r in records if r.get("expected_safety")]
    return {
        "samples": len(samples),
        "answered": answered,
        "correct": correct,
        "accuracy": ratio(correct, len(samples)),
        "accuracy_answered": ratio(correct, answered),
        "fallback": sum(1 for r in samples if r.get("provider") == "fallback"),
        "mock": len(all_samples) - len(samples),
        "http_errors": sum(1 for r in samples if r.get("status_code") != 200),
        "by_label": {k: {"samples": len(v), "correct": sum(1 for r in v if _attitude(r) == k), "accuracy": ratio(sum(1 for r in v if _attitude(r) == k), len(v))} for k, v in sorted(by_label.items())},
        "confusion": {k: dict(c) for k, c in sorted(matrix.items())},
        "confusions": [
            {"turn": r["turn"], "id": r.get("sample_id"), "input": r.get("example"), "expected": r["expected_attitude"], "predicted": _attitude(r), "provider": r.get("provider")}
            for r in samples
            if _attitude(r) != r["expected_attitude"]
        ],
        "override_cases": len(override),
        "override_safety_notice": sum(1 for r in override if r.get("safety_notice")),
    }


# 홍보 규칙(기획서 7장): R1 적응 구간(학식·동아리), R2 중간고사(도서관), R3 방학 계획(진로 4종)
PROMO_RULES = {
    "rag_dining_cafeteria_menu": "R1",
    "rag_clubs_yu_general_union": "R1",
    "rag_library_central": "R2",
    "rag_career_center": "R3",
    "rag_international_office": "R3",
    "rag_student_life_yutopia": "R3",
    "rag_startup_incubation": "R3",
}
CC_CHOICE_ID = "c4_t7_c"


def puruma_signals(records: list[dict]) -> dict:
    """10턴 진행에서 홍보 R1~R3·CC 분기·10턴 진로·엔딩이 실제로 나왔는지(대사 없음, 코드만)."""
    ok = [r for r in records if r.get("status_code") == 200]
    promos = Counter(r["promo_id"] for r in ok if r.get("promo_id"))
    rules = Counter(PROMO_RULES.get(p, "기타") for p in (r["promo_id"] for r in ok if r.get("promo_id")))
    cc = [r for r in ok if r.get("choice_id") == CC_CHOICE_ID]
    paths = Counter(((r.get("meta") or {}).get("puruma") or {}).get("path") for r in ok if r.get("turn") == 10)
    endings = Counter(r.get("ending") for r in ok if r.get("ending"))
    conversations = {(r.get("repeat"), r.get("conversation")) for r in records}
    return {
        "conversations": len(conversations),
        "promo_by_id": dict(promos),
        "promo_by_rule": {k: rules.get(k, 0) for k in ("R1", "R2", "R3")},
        "cc_branch_turns": len(cc),
        "cc_line_appended": sum(1 for r in cc if ((r.get("meta") or {}).get("fixed_lines_appended") or 0) > 0),
        "final_paths": {str(k): v for k, v in paths.items()},
        "endings": dict(endings),
        "emotion_codes": dict(Counter(r.get("emotion") for r in ok if r.get("emotion"))),
    }


# --------------------------------------------------------------------------- #
# 공급자 실패 시각 분포
# --------------------------------------------------------------------------- #
def failure_kind(record: dict) -> str | None:
    """503·429·시간 초과 등 공급자 실패 분류. 고정 대사 대체 사유 또는 HTTP 오류에서 정한다."""
    reason = (record.get("meta") or {}).get("fallback_reason")
    if record.get("provider") == "fallback":
        return reason or "fallback_unknown"
    if record.get("kind") in LLM_KINDS and record.get("status_code") not in (None, 200):
        return f"http_{record.get('status_code')}"
    return None


def failure_events(records: list[dict]) -> list[dict]:
    """실패 턴 목록(요청 시각 KST 순). 대사·입력은 없다."""
    events = [
        {"at": r.get("at"), "suite": r.get("suite"), "project": r.get("project"), "turn": r.get("turn"), "kind": failure_kind(r),
         "generation_calls": _gen(r).get("calls"), "violations": _gen(r).get("violations") or []}
        for r in records
        if failure_kind(r)
    ]
    return sorted(events, key=lambda e: e["at"] or "")


def time_bucket(at: str | None, minutes: int = 10) -> str:
    """'2026-11-22T14:37:05+09:00' → '2026-11-22 14:30'."""
    if not at or len(at) < 16:
        return "unknown"
    hour, minute = at[11:13], int(at[14:16])
    return f"{at[:10]} {hour}:{minute - minute % minutes:02d}"


def failure_timeline(records: list[dict], minutes: int = 10) -> dict:
    """시간대(기본 10분)별 LLM 턴 수와 실패 분류별 개수. 시간대 영향(503 몰림)을 보는 용도."""
    buckets: dict[str, Counter] = defaultdict(Counter)
    for r in llm_turns(records):
        bucket = time_bucket(r.get("at"), minutes)
        buckets[bucket]["llm_turns"] += 1
        kind = failure_kind(r)
        if kind:
            buckets[bucket][kind] += 1
    return {"minutes": minutes, "buckets": {k: dict(v) for k, v in sorted(buckets.items())}}


# --------------------------------------------------------------------------- #
# 서버 로그의 Gemini HTTP 시도(재시도로 회복된 503까지 보인다)
# --------------------------------------------------------------------------- #
import re as _re

_LOG_TIME = r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}),\d+ \| \w+\s*\| app\.services\.llm\.gemini_provider \| "
_LOG_STATUS = _re.compile(_LOG_TIME + r"provider=gemini model=(?P<model>\S+) operation=generateContent attempt=(?P<attempt>\d+) status=(?P<status>\d+) headers_ms=\S+ latency_ms=(?P<latency>\d+)")
_LOG_ERROR = _re.compile(_LOG_TIME + r"provider=gemini model=(?P<model>\S+) operation=generateContent attempt=(?P<attempt>\d+) error=(?P<error>\w+) phase=(?P<phase>\w+)")


def parse_gemini_http_log(lines, tz_suffix: str = "+09:00") -> list[dict]:
    """서버 로그(app.core.logging 형식, 서버 로컬 시각)에서 generateContent HTTP 시도만 뽑는다. 대사·키는 로그에 없다."""
    events = []
    for line in lines:
        m = _LOG_STATUS.match(line)
        if m:
            events.append({"at": f"{m['date']}T{m['time']}{tz_suffix}", "model": m["model"], "attempt": int(m["attempt"]), "status": int(m["status"]), "latency_ms": int(m["latency"])})
            continue
        m = _LOG_ERROR.match(line)
        if m:
            events.append({"at": f"{m['date']}T{m['time']}{tz_suffix}", "model": m["model"], "attempt": int(m["attempt"]), "status": m["error"], "phase": m["phase"]})
    return events


def http_log_summary(events: list[dict], minutes: int = 10) -> dict:
    """HTTP 시도 수·상태별 개수·10분 단위 분포. 상태가 200이 아닌 시도만 사건 목록으로 남긴다."""
    by_status = Counter(str(e["status"]) for e in events)
    buckets: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        bucket = time_bucket(e["at"], minutes)
        buckets[bucket]["requests"] += 1
        if e["status"] != 200:
            buckets[bucket][str(e["status"])] += 1
    return {
        "requests": len(events),
        "retries": sum(1 for e in events if e["attempt"] > 1),
        "by_status": dict(sorted(by_status.items())),
        "minutes": minutes,
        "buckets": {k: dict(v) for k, v in sorted(buckets.items())},
        "non_200": [e for e in events if e["status"] != 200],
    }
