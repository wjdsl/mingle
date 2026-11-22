"""Export run records, prepare blinded reviews and summarize without model calls."""
from contextlib import closing
import argparse
import hashlib
import json
import math
import sqlite3
import statistics
from pathlib import Path

from run_benchmark import HERE, METRICS, MODELS, digest, load_suite, pack, run_records

WEIGHTS = dict(zip((*METRICS, "efficiency"), (.30, .25, .20, .15, .10)))
SPEAKERS = {"fridge": {"냉장고 회장"}, "puruma": {"푸르마"}, "cloud": {"토토", "비비", "나나", "키키", "두두"}}


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


def automatic(case, response, contexts):
    if case.get("fixed"):
        return [] if response == contexts[case["project"]]["fixed"] else ["fixed_text_changed"]
    # Recognize only line-leading speaker labels; bracketed stage directions may have colons.
    labels = [l.split(":", 1)[0].strip() for l in response.splitlines()
              if ":" in l and not l.startswith(("[", "("))]
    allowed = SPEAKERS[case["project"]]
    issues = []
    if not labels or set(labels)-allowed:
        issues.append("speaker_format")
    if len(labels) > min(3, len(allowed)) or len(labels) != len(set(labels)):
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


def summarize(model, ids, latest, attempts, reviews, auto):
    rows = [r for r in attempts if r["model"] == model]
    resolved = [r for r in rows if r["status"] != "uncertain"]
    errors = [r for r in resolved if r["status"] == "error"]
    successes = [latest[model, cid] for cid in ids if (model, cid) in latest and latest[model,cid]["status"] == "ok"]
    latency = [r["latency_s"] for r in successes if r.get("latency_s") is not None]
    complete = len(successes) == len(ids)
    metrics, counts = {}, {}
    for metric in METRICS:
        paired = [reviews[model,cid]["scores"][metric] for cid in ids
                  if all(type(reviews.get((m,cid), {}).get("scores", {}).get(metric)) is int for m in MODELS)]
        metrics[metric] = mean(paired)
        counts[metric] = len(paired)
    error_rate = len(errors)/len(resolved) if resolved else None
    usable = len([r for r in resolved if r["status"] == "ok"])/len(resolved) if resolved else None
    metrics["efficiency"] = mean([latency_grade(s) for s in latency])*usable if latency else None
    reviewed = [v for (m,_),v in reviews.items() if m == model]
    all_reviewed = complete and all(
        None not in v["scores"].values() and v["extra_violations"] is not None and v["severe_violations"] is not None
        for v in reviewed)
    human_complete = bool(reviewed) and all(v["extra_violations"] is not None for v in reviewed)
    severe_complete = bool(reviewed) and all(v["severe_violations"] is not None for v in reviewed)
    auto_count = sum(len(v) for (m,_),v in auto.items() if m == model)
    tokens = {}
    for label, key in [("input","promptTokenCount"), ("output","candidatesTokenCount"), ("thinking","thoughtsTokenCount")]:
        values = [r["usage"][key] for r in resolved if isinstance(r.get("usage", {}).get(key), int)]
        tokens[label] = {"observed": len(values), "total": sum(values) if values else None, "mean": mean(values)}
    return {"planned": len(ids), "attempts": len(rows), "ok": len(successes),
            "api_errors": len(errors), "api_error_rate": error_rate,
            "invalid_outputs": sum(r["status"]=="invalid" for r in rows),
            "uncertain": len(rows)-len(resolved), "latency_s": {"mean":mean(latency),
                "median":statistics.median(latency) if latency else None,"p95":p95(latency)},
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
    out.mkdir(exist_ok=True)
    save(out / "responses.json", {"manifest": manifest, "attempts": rows})
    latest = {(r["model"],r["test_id"]):r for r in rows}
    cases = {c["id"]:c for c in suite["cases"]}
    filename = out / "reviews.json"
    forms = json.loads(filename.read_text()) if filename.exists() else {}
    reviews, auto, by_test = {}, {}, []
    for key, row in latest.items():
        model,cid = key
        if row["status"] != "ok":
            continue
        case = cases[cid]
        blind = hashlib.sha256(pack([phase, model, cid, row["response"]]).encode()).hexdigest()[:16]
        if blind not in forms:
            forms[blind] = review_form(case, row, contexts[case["project"]])
        validate(forms[blind])
        reviews[key] = forms[blind]
        auto[key] = automatic(case,row["response"],contexts)
        by_test.append({"model":model,"test_id":cid,"automatic":auto[key],
                        **{k:forms[blind][k] for k in ("scores","extra_violations","severe_violations","comment")}})
    save(filename, dict(sorted(forms.items())))
    ids = manifest["cases"]
    result = {m:summarize(m,ids,latest,rows,reviews,auto) for m in MODELS}
    real_full = manifest["mode"] == "live" and phase == "full"
    if real_full and all(v["fully_reviewed"] and None not in v["metrics"].values() for v in result.values()):
        for v in result.values():
            v["weighted"] = sum(WEIGHTS[k]*score for k,score in v["metrics"].items())
    report = {"mode":manifest["mode"],"phase":phase,"models":result,"by_test":by_test}
    save(out/"summary.json", report)
    lines = [f"# {manifest['mode']} / {phase}", "", "| 항목 | "+" | ".join(MODELS)+" |",
             "|---|---:|---:|"]
    def add(label, values):
        cells = ["N/A" if x is None else f"{x:.3f}" if isinstance(x,float) else str(x) for x in values]
        lines.append("| "+" | ".join([label,*cells])+" |")
    for k in ("planned","attempts","ok","api_errors","api_error_rate","invalid_outputs","uncertain",
              "automatic_violations","violations","severe","weighted"):
        add(k,[v[k] for v in result.values()])
    for k in WEIGHTS:
        add(k,[v["metrics"][k] for v in result.values()])
    for k in ("mean","median","p95"):
        add(k+" (s)",[v["latency_s"][k] for v in result.values()])
    for k in ("input","output","thinking"):
        add(k+" tokens",[v["tokens"][k]["total"] for v in result.values()])
    (out/"comparison.md").write_text("\n".join(lines)+"\n")
    print(out/"comparison.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock","live"), required=True)
    parser.add_argument("--phase", choices=("probe","full"), required=True)
    parser.add_argument("--results", type=Path, default=HERE/"results")
    args = parser.parse_args()
    evaluate(args.results/args.mode, args.phase)
