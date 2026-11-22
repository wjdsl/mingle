"""Export run records, prepare blinded reviews and summarize without model calls."""
from contextlib import closing
import argparse
import hashlib
import json
import math
import re
import sqlite3
import statistics
from pathlib import Path

from run_benchmark import HERE, METRICS, MODELS, digest, ensure_ignored_outputs, load_suite, pack, run_records

WEIGHTS = dict(zip((*METRICS, "efficiency"), (.30, .25, .20, .15, .10)))
CLOUD_LINE = re.compile(r"^(토토|비비|나나|키키|두두)[:：]\s*(\S.*)$")
TOKEN_FIELDS = {
    "input": "promptTokenCount",
    "output": "candidatesTokenCount",
    "thinking": "thoughtsTokenCount",
    "total": "totalTokenCount",
}


def save(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def mean(values):
    return statistics.mean(values) if values else None


def p95(values):
    return sorted(values)[math.ceil(len(values)*.95)-1] if values else None


def latency_grade(seconds):
    return sum(seconds <= cutoff for cutoff in (2, 4, 8, 16, 30))


def token_count(row, field):
    count = (row.get("usage") or {}).get(field)
    return count if type(count) is int and count >= 0 else None


def token_stats(values):
    return {"observed": len(values), "total": sum(values) if values else None, "mean": mean(values)}


def latency_stats(values):
    return {"observed": len(values), "mean": mean(values),
            "median": statistics.median(values) if values else None, "p95": p95(values)}


def paired_performance(ids, latest, fixed_ids):
    pair_count = 0
    measurements = {label: [[] for _ in MODELS] for label in ("latency_s", *TOKEN_FIELDS)}
    for cid in ids:
        pair = [latest.get((model, cid)) for model in MODELS]
        if cid in fixed_ids or any(row is None or row["status"] != "ok" for row in pair):
            continue
        pair_count += 1
        fields = {"latency_s": [row.get("latency_s") for row in pair]}
        fields.update({label: [token_count(row, field) for row in pair] for label, field in TOKEN_FIELDS.items()})
        for label, values in fields.items():
            if None not in values:
                for observations, value in zip(measurements[label], values):
                    observations.append(value)
    return {
        model: {"successful_pairs": pair_count,
                "latency_s": latency_stats(measurements["latency_s"][i]),
                "tokens": {label: token_stats(measurements[label][i]) for label in TOKEN_FIELDS}}
        for i, model in enumerate(MODELS)
    }


def automatic(case, response):
    issues = []
    if case["project"] == "cloud":
        lines = [line.strip() for line in response.splitlines() if line.strip()]
        speakers = [match[1] for line in lines if (match := CLOUD_LINE.fullmatch(line))]
        if not speakers or len(speakers) != len(lines):
            issues.append("speaker_format")
        if len(speakers) > 3 or len(speakers) != len(set(speakers)):
            issues.append("speaker_count")
    if "{{user}}" in response:
        issues.append("nickname_placeholder")
    return issues


def read_run(folder, phase):
    with closing(sqlite3.connect((folder / "runs.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return run_records(db, phase)


def review_form(case, row, context):
    return {"test_id": case["id"], "character": case["character"], "type": case["type"],
            "scene": context["scenes"][case["scene"]-1], "expected": case["expected"],
            "forbidden": case["forbidden"], "criterion": case["criterion"],
            "system": row["request"]["systemInstruction"], "conversation": row["request"]["contents"],
            "response": row["response"], "scores": {k: None for k in METRICS},
            "extra_violations": None, "severe_violations": None, "comment": ""}


def validate(review):
    scores = review["scores"]
    if set(scores) != set(METRICS):
        raise ValueError("scores 항목 이름을 확인하세요.")
    for score in scores.values():
        if score not in (None, "N/A") and (type(score) is not int or not 0 <= score <= 5):
            raise ValueError("품질 점수는 0~5 정수, N/A 또는 null이어야 합니다.")
    for k in ("extra_violations", "severe_violations"):
        n = review[k]
        if n is not None and (type(n) is not int or n < 0):
            raise ValueError("위반 횟수는 음이 아닌 정수 또는 null이어야 합니다.")


def summarize(model, ids, latest, attempts, reviews, auto, fixed_ids=()):
    rows = [r for r in attempts if r["model"] == model]
    resolved = [r for r in rows if r["status"] != "uncertain"]
    errors = [r for r in resolved if r["status"] == "error"]
    successes = [latest[model, cid] for cid in ids if (model, cid) in latest and latest[model,cid]["status"] == "ok"]
    generated = [row for row in successes if row["test_id"] not in fixed_ids]
    latency = [row["latency_s"] for row in generated if row.get("latency_s") is not None]
    quality_ids = [cid for cid in ids if cid not in fixed_ids]
    metrics, counts = {}, {}
    for metric in METRICS:
        paired = [reviews[model,cid]["scores"][metric] for cid in quality_ids
                  if all(type(reviews.get((m,cid), {}).get("scores", {}).get(metric)) is int for m in MODELS)]
        metrics[metric] = mean(paired)
        counts[metric] = len(paired)
    error_rate = len(errors)/len(resolved) if resolved else None
    generated_attempts = [row for row in resolved if row["test_id"] not in fixed_ids]
    usable = (sum(row["status"] == "ok" for row in generated_attempts) / len(generated_attempts)
              if generated_attempts else None)
    metrics["efficiency"] = mean([latency_grade(s) for s in latency])*usable if latency else None
    reviewed = [v for (m,_),v in reviews.items() if m == model]
    all_reviewed = len(generated) == len(quality_ids) and len(reviewed) == len(quality_ids) and all(
        None not in v["scores"].values() and v["extra_violations"] is not None and v["severe_violations"] is not None
        for v in reviewed)
    human_complete = bool(reviewed) and all(v["extra_violations"] is not None for v in reviewed)
    severe_complete = bool(reviewed) and all(v["severe_violations"] is not None for v in reviewed)
    auto_count = sum(len(v) for (m,_),v in auto.items() if m == model)
    tokens = {
        label: token_stats([count for row in resolved if (count := token_count(row, field)) is not None])
        for label, field in TOKEN_FIELDS.items()
    }
    return {"planned": len(ids), "attempts": len(rows), "ok": len(successes),
            "quality_planned": len(quality_ids), "quality_ok": len(generated),
            "human_violation_reviews": sum(v["extra_violations"] is not None for v in reviewed),
            "severe_reviews": sum(v["severe_violations"] is not None for v in reviewed),
            "api_errors": len(errors), "api_error_rate": error_rate,
            "invalid_outputs": sum(r["status"]=="invalid" for r in rows),
            "uncertain": len(rows)-len(resolved), "latency_s": latency_stats(latency),
            "model_versions": sorted({row["model_version"] for row in generated if row.get("model_version")}),
            "model_version_observed": sum(bool(row.get("model_version")) for row in generated),
            "tokens": tokens, "automatic_violations": auto_count,
            "violations": auto_count+sum(v["extra_violations"] for v in reviewed) if human_complete else None,
            "severe": sum(v["severe_violations"] for v in reviewed) if severe_complete else None,
            "metrics": metrics, "paired_counts": counts, "fully_reviewed": all_reviewed, "weighted": None}


def evaluate(folder, phase):
    suite, contexts = load_suite()
    manifest, rows = read_run(folder.resolve(), phase)
    if manifest["suite_hash"] != digest(pack(suite)) or manifest["context_hash"] != digest(pack(contexts)):
        raise ValueError("이 실행에서 사용한 테스트셋과 프롬프트 버전이 필요합니다.")
    out = folder / phase
    artifacts = ("responses.json", "reviews.json", "summary.json", "comparison.md")
    ensure_ignored_outputs(*(out / name for name in (*artifacts, "responses.tmp", "reviews.tmp", "summary.tmp")))
    out.mkdir(exist_ok=True)
    save(out / "responses.json", {"manifest": manifest, "attempts": rows})
    latest = {(r["model"],r["test_id"]):r for r in rows}
    cases = {c["id"]:c for c in suite["cases"]}
    filename = out / "reviews.json"
    forms = json.loads(filename.read_text()) if filename.exists() else {}
    reviews, auto, by_test = {}, {}, []
    fixed_ids = {case["id"] for case in cases.values() if case.get("fixed")}
    fixed = {model: [] for model in MODELS}
    for model in MODELS:
        for cid in manifest["cases"]:
            if cid not in fixed_ids:
                continue
            row = latest.get((model, cid))
            status = row["status"] if row else "pending"
            exact = None
            if status == "ok" and manifest["mode"] == "live":
                exact = row["response"] == contexts[cases[cid]["project"]]["fixed"]
            fixed[model].append({"test_id": cid, "status": status, "exact_match": exact})
    for key, row in latest.items():
        model,cid = key
        if row["status"] != "ok" or cid in fixed_ids:
            continue
        case = cases[cid]
        blind = hashlib.sha256(pack([phase, model, cid, row["response"]]).encode()).hexdigest()[:16]
        if blind not in forms:
            forms[blind] = review_form(case, row, contexts[case["project"]])
        validate(forms[blind])
        reviews[key] = forms[blind]
        auto[key] = automatic(case, row["response"])
        by_test.append({"model":model,"test_id":cid,"automatic":auto[key],
                        **{k:forms[blind][k] for k in ("scores","extra_violations","severe_violations")}})
    save(filename, dict(sorted(forms.items())))
    ids = manifest["cases"]
    result = {m:summarize(m, ids, latest, rows, reviews, auto, fixed_ids) for m in MODELS}
    real_full = manifest["mode"] == "live" and phase == "full"
    if real_full and all(v["fully_reviewed"] and None not in v["metrics"].values() for v in result.values()):
        for v in result.values():
            v["weighted"] = sum(WEIGHTS[k]*score for k,score in v["metrics"].items())
    paired = paired_performance(ids, latest, fixed_ids)
    report = {"mode":manifest["mode"],"phase":phase,"models":result,"by_test":by_test,
              "fixed_reproduction":fixed,"paired_performance":paired}
    save(out/"summary.json", report)
    lines = [f"# {manifest['mode']} / {phase}", "", "| 항목 | "+" | ".join(MODELS)+" |",
             "|---|---:|---:|"]
    def add(label, values):
        cells = ["N/A" if x is None else f"{x:.3f}" if isinstance(x,float) else str(x) for x in values]
        lines.append("| "+" | ".join([label,*cells])+" |")
    for k in ("planned","attempts","ok","api_errors","api_error_rate","invalid_outputs","uncertain",
              "quality_planned","quality_ok","human_violation_reviews","severe_reviews",
              "automatic_violations","violations","severe","weighted"):
        add(k,[v[k] for v in result.values()])
    for k in WEIGHTS:
        add(k,[v["metrics"][k] for v in result.values()])
    for k in ("mean","median","p95"):
        add("generated "+k+" (s)",[v["latency_s"][k] for v in result.values()])
    add("관측 모델 버전", [", ".join(v["model_versions"]) or None for v in result.values()])
    add("모델 버전 관측 수", [v["model_version_observed"] for v in result.values()])
    for label in TOKEN_FIELDS:
        add(f"{label} 토큰 합계 (전체 확인 시도)", [v["tokens"][label]["total"] for v in result.values()])
        add(f"{label} 토큰 관측 수 (전체 확인 시도)", [v["tokens"][label]["observed"] for v in result.values()])
    lines.extend(["", "## 두 모델이 모두 성공한 생성 문항", "",
                  "| 항목 | "+" | ".join(MODELS)+" |", "|---|---:|---:|"])
    add("성공 문항 쌍", [v["successful_pairs"] for v in paired.values()])
    for key in ("observed", "mean", "median", "p95"):
        add(f"지연 {key}", [v["latency_s"][key] for v in paired.values()])
    for label in TOKEN_FIELDS:
        add(f"{label} 토큰 평균", [v["tokens"][label]["mean"] for v in paired.values()])
        add(f"{label} 토큰 관측 쌍", [v["tokens"][label]["observed"] for v in paired.values()])
    if any(fixed.values()):
        lines.extend(["", "## 고정 컷 원문 재현", "", "| 문항 | "+" | ".join(MODELS)+" |", "|---|---:|---:|"])
        for i, item in enumerate(fixed[MODELS[0]]):
            add(item["test_id"], [fixed[model][i]["exact_match"] for model in MODELS])
    (out/"comparison.md").write_text("\n".join(lines)+"\n")
    print(out/"comparison.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock","live"), required=True)
    parser.add_argument("--phase", choices=("probe","full"), required=True)
    parser.add_argument("--results", type=Path, default=HERE/"results")
    args = parser.parse_args()
    evaluate(args.results/args.mode, args.phase)
