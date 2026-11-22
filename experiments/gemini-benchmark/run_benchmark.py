"""MINGLE paired benchmark. Python 3.10+, macOS/Linux, standard library only."""
import argparse
import fcntl
import hashlib
import http.client
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
MODELS = ("gemini-3.5-flash-lite", "gemini-3.6-flash")
# Project owner's AI Studio snapshot, 2026-11-22. RPM, RPD, input TPM.
LIMITS = dict(zip(MODELS, [(15, 500, 250_000), (5, 20, 250_000)]))
CONFIG = {"temperature": 1.0, "maxOutputTokens": 512, "thinkingConfig": {"thinkingLevel": "minimal"}}
HOST = "generativelanguage.googleapis.com"
PACIFIC = ZoneInfo("America/Los_Angeles")
METRICS = ("persona", "compliance", "memory", "naturalness")


def pack(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data):
    return hashlib.sha256(data.encode()).hexdigest()


def load_suite():
    suite = json.loads((HERE / "test_cases.json").read_text())
    contexts = json.loads((HERE / "prompt_context.json").read_text())
    return suite, contexts


def message(role, text):
    return {"role": role, "parts": [{"text": text}]}


def make_request(case, contexts, previous):
    context = contexts[case["project"]]
    instruction = (context["rules"] + "\n현재 장면\n" + context["scenes"][case["scene"] - 1]
                   + "\n표시 호칭은 솔빛이다. 푸르마는 기본 호칭 선배를 쓴다. "
                   "한국어로 각 화자의 이름과 콜론, 대사를 쓴다. 한 화자당 1~3문장. "
                   "구름섬은 1~3명, 다른 작품은 한 명만 말한다. 평가 설명이나 선택지는 출력하지 않는다.")
    if case.get("fixed"):
        instruction += "\n이 턴은 재생 전용이다. 다음 원문만 정확히 출력한다.\n" + context["fixed"]
    instruction += "\n합성 유저노트: " + pack(case["notes"]) + "\n고정 검색 자료: " + pack(case["rag"])
    contents = [message("user" if i % 2 == 0 else "model", t) for i, t in enumerate(case["history"])]
    for prior in previous:
        contents.extend([message("user", prior["input"]), message("model", prior["response"])])
    contents.append(message("user", case["input"]))
    return {"systemInstruction": {"parts": [{"text": instruction}]}, "contents": contents,
            "generationConfig": CONFIG}


def key_from(path):
    if path:
        for line in path.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip("'\"")
                if key:
                    return key
        raise ValueError("키 파일에 GEMINI_API_KEY 값이 없습니다.")
    if not os.environ.get("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY 또는 --env-file이 필요합니다.")
    return os.environ["GEMINI_API_KEY"]


def google(model, key, body=None):
    path = "/v1beta/models/" + model
    conn = http.client.HTTPSConnection(HOST, timeout=60)
    try:
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        if body is None:
            conn.request("GET", path, headers=headers)
        else:
            conn.request("POST", path + ":generateContent", pack(body).encode(), headers)
        res = conn.getresponse()
        raw = res.read()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            return {"status": "error", "http": res.status, "error": "NON_JSON_RESPONSE",
                    "retry_after": res.getheader("Retry-After")}
        if res.status != 200:
            error = data.get("error", {})
            return {"status": "error", "http": res.status, "error": error.get("status", "HTTP_ERROR"),
                    "quota_ids": [v.get("quotaId") for d in error.get("details", [])
                                  for v in d.get("violations", [])], "retry_after": res.getheader("Retry-After")}
        if body is None:
            fields = ("name", "version", "supportedGenerationMethods", "inputTokenLimit", "outputTokenLimit",
                      "temperature", "topP", "topK", "thinking")
            return {"status": "ok", "http": 200, **{k: data.get(k) for k in fields}}
        candidate = next(iter(data.get("candidates", [])), {})
        parts = candidate.get("content", {}).get("parts", [])
        response = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        finish = candidate.get("finishReason")
        return {"status": "ok" if response and finish == "STOP" else "invalid", "http": 200,
                "response": response, "finish": finish, "model_version": data.get("modelVersion"),
                "usage": data.get("usageMetadata", {}), "block": data.get("promptFeedback", {}).get("blockReason")}
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return {"status": "error", "error": type(exc).__name__}
    finally:
        conn.close()


def open_db(folder):
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "runs.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS manifests
               (phase TEXT PRIMARY KEY, fingerprint TEXT, manifest TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS attempts
               (phase TEXT, model TEXT, case_id TEXT, attempt INTEGER, started REAL,
                budget INTEGER, payload TEXT, result TEXT,
                PRIMARY KEY(phase,model,case_id,attempt))""")
    return db


def run_records(db, phase):
    manifest_row = db.execute("SELECT manifest FROM manifests WHERE phase=?", (phase,)).fetchone()
    if not manifest_row:
        raise ValueError("선택한 단계의 기록이 없습니다.")
    manifest = json.loads(manifest_row[0])
    rows = []
    for r in db.execute("SELECT * FROM attempts WHERE phase=? ORDER BY started,rowid", (phase,)):
        rows.append({"model": r["model"], "test_id": r["case_id"], "attempt": r["attempt"],
                     "timestamp": datetime.fromtimestamp(r["started"], timezone.utc).isoformat(),
                     "request": json.loads(r["payload"]), **(json.loads(r["result"]) if r["result"]
                        else {"status": "uncertain"})})
    return manifest, rows


def reserve(db, phase, model, case, body):
    args = (phase, model, case["id"])
    number = db.execute("SELECT count(*) FROM attempts WHERE phase=? AND model=? AND case_id=?", args).fetchone()[0]+1
    # UTF-8 byte count plus generous framing allowance, independent of tokenization.
    budget = len(pack(body).encode()) + 1024
    started = time.time()
    with db:
        db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,NULL)",
                   (*args, number, started, budget, pack(body)))
    return number


def quota_wait(db, model, body):
    rpm, rpd, tpm = LIMITS[model]
    budget = len(pack(body).encode()) + 1024
    if budget > tpm:
        return "입력 1건이 TPM 예약 한도를 초과합니다."
    while True:
        now = time.time()
        midnight = datetime.fromtimestamp(now, PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
        today = db.execute("SELECT count(*) FROM attempts WHERE model=? AND started>=?",
                           (model, midnight.timestamp())).fetchone()[0]
        if today >= rpd:
            return "로컬 RPD 도달. 태평양 시간 자정 이후 재개하세요."
        minute = db.execute("SELECT started,budget FROM attempts WHERE model=? AND started>? ORDER BY started",
                            (model, now-60)).fetchall()
        if minute and (len(minute) >= rpm or sum(row["budget"] for row in minute)+budget > tpm):
            time.sleep(max(0.05, minute[0]["started"]+60.05-now))
        elif minute and minute[-1]["started"] + 60/rpm > now:
            time.sleep(minute[-1]["started"] + 60/rpm - now)
        else:
            return None


def latest(db, phase, model, cid):
    row = db.execute("""SELECT result,started FROM attempts WHERE phase=? AND model=? AND case_id=?
                      ORDER BY attempt DESC LIMIT 1""", (phase, model, cid)).fetchone()
    if row is None:
        return None
    return {**(json.loads(row["result"]) if row["result"] else {"status": "uncertain"}), "started": row["started"]}


def plan(cases, phase):
    chosen = cases[:1] if phase == "probe" else cases
    for i, case in enumerate(chosen):
        for model in MODELS[::1 if i % 2 == 0 else -1]:
            yield model, case


def run(args):
    suite, contexts = load_suite()
    jobs = list(plan(suite["cases"], args.phase))
    print(f"{args.phase} 기본 생성 {len(jobs)}건, 모델당 {len(jobs)//2}건. 전송 방식 {args.mode}", flush=True)
    if args.mode == "dry-run":
        for model, case in jobs:
            make_request(case, contexts, [])
        print("실제 전송 0건")
        return 0
    live = args.mode == "live"
    folder = args.results / args.mode
    db = open_db(folder)
    try:
        with (folder / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                return execute(args, db, suite, contexts, jobs, live)
            finally:
                if db.execute("SELECT 1 FROM manifests WHERE phase=?", (args.phase,)).fetchone():
                    manifest, attempts = run_records(db, args.phase)
                    output = folder / args.phase
                    output.mkdir(exist_ok=True)
                    tmp = output / "responses.exporting"
                    tmp.write_text(json.dumps({"manifest": manifest, "attempts": attempts},
                                              ensure_ascii=False, indent=2) + "\n")
                    tmp.replace(output / "responses.json")
    finally:
        db.close()


def execute(args, db, suite, contexts, jobs, live):
    key = None
    if live:
        if not args.confirm_free_tier:
            raise ValueError("현재 키의 Free tier 확인 후 --confirm-free-tier가 필요합니다.")
        key = key_from(args.env_file)
    manifest = {"prompt_version": suite["version"], "source_commit": suite["source_commit"],
                "mode": args.mode, "phase": args.phase, "models": MODELS, "config": CONFIG, "limits": LIMITS,
                "suite_hash": digest(pack(suite)), "context_hash": digest(pack(contexts)),
                "runner_hash": digest(Path(__file__).read_text()), "cases": [c["id"] for c in suite["cases"]
                    if args.phase == "full" or c == suite["cases"][0]]}
    fingerprint = digest(pack(manifest))
    with db:
        db.execute("INSERT OR IGNORE INTO manifests VALUES (?,?,?)", (args.phase, fingerprint, pack(manifest)))
    saved = db.execute("SELECT fingerprint FROM manifests WHERE phase=?", (args.phase,)).fetchone()[0]
    if saved != fingerprint:
        original = json.loads(db.execute("SELECT manifest FROM manifests WHERE phase=?", (args.phase,)).fetchone()[0])
        # Allow reading a completed archive after runner maintenance. Never append to it.
        requested = json.loads(pack(manifest))
        requested.pop("runner_hash")
        original.pop("runner_hash")
        if original == requested and all((latest(db, args.phase, m, c["id"]) or {}).get("status") == "ok"
                                         for m, c in jobs):
            print("이미 완료한 실행입니다. 신규 요청 0건.")
            return 0
        raise ValueError("실행 설정 또는 입력이 바뀌었습니다. 원래 버전에서 재개하세요.")
    todo = sum(latest(db, args.phase, m, c["id"]) is None for m,c in jobs)
    print(f"미시도 {todo}건. 이번 실행 상한 {args.max_calls or len(jobs)}건.", flush=True)
    histories = {}
    calls = 0
    incomplete = False
    for model, case in jobs:
        cid = case["id"]
        history = histories.setdefault((model, case["project"]), []) if case["type"] == "multi" else []
        if case["type"] == "multi" and len(history) != case["scene"]-1:
            incomplete = True
            continue
        result = latest(db, args.phase, model, cid)
        if result and result.get("http") == 429 and args.phase == "full" and args.retry_quota:
            if datetime.fromtimestamp(result["started"], PACIFIC).date() < datetime.now(PACIFIC).date():
                result = None
        if result is None:
            if args.max_calls and calls >= args.max_calls:
                return 2
            body = make_request(case, contexts, history)
            if live:
                stop = quota_wait(db, model, body)
                if stop:
                    print(model, stop)
                    return 2
            number = reserve(db, args.phase, model, case, body)
            start = time.monotonic()
            if live:
                result = google(model, key, body)
            else:
                result = {"status": "ok", "response": f"[MOCK] {model} {cid}", "usage": {}}
            result["latency_s"] = round(time.monotonic()-start, 6) if live else None
            with db:
                db.execute("UPDATE attempts SET result=? WHERE phase=? AND model=? AND case_id=? AND attempt=?",
                           (pack(result), args.phase, model, cid, number))
            calls += 1
            print(model, cid, result["status"], result.get("http", ""), flush=True)
            if result.get("http") == 429:
                return 2
        if result["status"] == "ok":
            history.append({"input": case["input"], "response": result["response"]})
        else:
            incomplete = True
    return 2 if incomplete else 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["dry-run", "mock", "live", "metadata"], default="dry-run")
    p.add_argument("--phase", choices=["probe", "full"], default="probe")
    p.add_argument("--results", type=Path, default=HERE / "results")
    p.add_argument("--env-file", type=Path)
    p.add_argument("--confirm-free-tier", action="store_true")
    p.add_argument("--retry-quota", action="store_true")
    p.add_argument("--max-calls", type=int)
    args = p.parse_args()
    if args.max_calls is not None and args.max_calls < 1:
        p.error("--max-calls must be positive")
    if args.mode == "metadata":
        key = key_from(args.env_file)
        records = {m: google(m, key) for m in MODELS}
        folder = args.results / "live"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"metadata-{time.time_ns()}.json"
        path.write_text(pack({"timestamp": datetime.now(timezone.utc).isoformat(), "models": records}))
        print(pack(records))
        return int(any(v.get("name") != "models/"+m or "generateContent" not in
                       (v.get("supportedGenerationMethods") or []) for m,v in records.items()))
    return run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.exit(str(exc))
