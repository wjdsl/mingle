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
