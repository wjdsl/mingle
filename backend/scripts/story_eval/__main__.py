"""평가 실행기 명령.

    python -m scripts.story_eval run --dry-run [--suites ...] [--repeat N] [--runs 2]
    python -m scripts.story_eval run --label NAME --max-calls N [--base-url URL] [--database-url URL]
    python -m scripts.story_eval compare A/report.json B/report.json [--out compare.md]

실제 공급자(gemini 등)로 실행할 때는 --max-calls가 필요하다. 먼저 --dry-run으로 예상 호출 수를 본다.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings
from scripts.story_eval.plan import PROJECTS, SCENE_SET, SUITES, build_plans, estimate_calls
from scripts.story_eval.report import DEFAULT_OUT_DIR, behavior_results, build_report, load_report, render_compare, write_run
from scripts.story_eval.runner import Budget, BudgetExceeded, RunAborted, RunState, StoryEvalRunner, TurnMetaReader

EXIT_OK, EXIT_ABORTED, EXIT_USAGE, EXIT_BUDGET = 0, 1, 2, 3


def _csv(value: str, allowed: tuple[str, ...]) -> list[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    bad = [v for v in items if v not in allowed]
    if bad or not items:
        raise argparse.ArgumentTypeError(f"허용 값: {', '.join(allowed)}")
    return [v for v in allowed if v in items]


def _bool(value: str) -> bool:
    if value.lower() in ("1", "true", "yes", "on"):
        return True
    if value.lower() in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError("true/false")


def print_estimate(estimate: dict, runs: int) -> None:
    a = estimate["assumptions"]
    print(f"예상 호출 수 (반복 {a['repeat']}회, 생성 시도 {a['story_generation_attempts']} × HTTP 재시도 {a['http_attempts']}, 냉장고 Qwen {'켜짐' if a['fridge_qwen'] else '꺼짐'})")
    print(f"{'스위트':10s} {'작품':7s} {'대화':>5s} {'LLM턴':>6s} {'고정':>5s} {'위기':>5s} {'최소':>6s} {'최대':>6s}")
    for r in estimate["rows"]:
        print(f"{r['suite']:10s} {r['project']:7s} {r['conversations']:5d} {r['llm_turns']:6d} {r['fixed_turns']:5d} {r['crisis_turns']:5d} {r['min_calls']:6d} {r['max_calls']:6d}")
    print(f"합계: LLM 턴 {estimate['total_llm_turns']}, 호출 최소 {estimate['total_min_calls']} ~ 최대 {estimate['total_max_calls']}")
    if runs > 1:
        print(f"모델 {runs}개 비교(실행 {runs}회): 최소 {estimate['total_min_calls'] * runs} ~ 최대 {estimate['total_max_calls'] * runs}")
    print("최소 = 모든 턴 첫 시도 통과. 최대 = 교정 재생성과 HTTP 재시도를 모두 소진. 위기 표현·10턴 고정 연출은 호출 0회.")
    print("서버 시작 점검(LLM_PROBE_ON_STARTUP=true)은 서버 프로세스마다 임베딩·생성 각 1회를 따로 호출한다.")


async def _run(args: argparse.Namespace) -> int:
    plans, cases = build_plans(args.suites, args.projects)
    estimate = estimate_calls(plans, repeat=args.repeat, story_attempts=args.story_attempts, http_attempts=args.http_attempts, qwen=args.qwen)
    print_estimate(estimate, args.runs)
    if args.dry_run:
        print("dry-run: 서버를 호출하지 않았습니다.")
        return EXIT_OK

    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout) as http:
        try:
            health = (await http.get("/api/health")).raise_for_status().json()
        except httpx.HTTPError as exc:
            print(f"서버에 연결할 수 없습니다({args.base_url}): {type(exc).__name__}")
            return EXIT_USAGE
        llm = health.get("llm") or {}
        server = {"provider": llm.get("provider"), "chat_model": llm.get("chat_model"), "degraded": llm.get("degraded"), "database": health.get("database"), "version": health.get("version")}
        print(f"서버: provider={server['provider']} model={server['chat_model']} degraded={server['degraded']} db={server['database']}")
        if server["provider"] != "mock" and args.max_calls is None:
            print("실제 공급자로 실행하려면 --max-calls가 필요합니다. 위 예상 최대 호출 수를 참고해 지정하세요.")
            return EXIT_USAGE
        if args.max_calls is not None and server["provider"] != "mock" and estimate["total_max_calls"] > args.max_calls:
            print(f"주의: 예상 최대 {estimate['total_max_calls']}회가 --max-calls {args.max_calls}보다 큽니다. 상한에 닿으면 그 앞에서 멈춥니다.")

        reader = None if args.no_db else TurnMetaReader(args.database_url or settings.database_url)
        budget = Budget(args.max_calls, args.story_attempts, args.http_attempts, args.qwen)
        runner = StoryEvalRunner(http, reader, budget, expect_provider=args.expect_provider or server["provider"], pause=args.pause)
        state = RunState()
        started = datetime.now().astimezone()
        status, stop_reason = "completed", None
        try:
            for repeat in range(1, args.repeat + 1):
                for index, plan in enumerate(plans):
                    await runner.run_conversation(plan, repeat=repeat, index=index, state=state)
        except BudgetExceeded as exc:
            status, stop_reason = "stopped_by_budget", str(exc)
        except RunAborted as exc:
            status, stop_reason = "aborted", str(exc)
        except httpx.HTTPError as exc:
            status, stop_reason = "aborted", f"HTTP 오류: {type(exc).__name__}"
        finally:
            if reader is not None:
                await reader.close()
        finished = datetime.now().astimezone()

    if state.aborted_conversations and status == "completed":
        status = "completed_with_errors"
    behavior, review = behavior_results([c for c in cases], state.behavior)
    label = args.label or (server["chat_model"] or "run")
    run = {
        "label": label,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "suites": args.suites,
        "projects": args.projects,
        "repeat": args.repeat,
        "scene_set": SCENE_SET,
        "status": status,
        "stop_reason": stop_reason,
        "skipped_steps": state.skipped_steps,
        "aborted_conversations": state.aborted_conversations,
        "db_metadata": not args.no_db,
    }
    assumed = {"story_generation_attempts": args.story_attempts, "http_attempts": args.http_attempts, "fridge_qwen_dialogue_enabled": args.qwen}
    report = build_report(run=run, server=server, assumed=assumed, budget=budget.as_dict(), plan_estimate=estimate, records=state.records, behavior=behavior)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "run"
    out_dir = Path(args.out_dir) / f"{started.strftime('%Y%m%d-%H%M%S')}_{slug}"
    paths = write_run(report, review, out_dir)
    print(f"상태: {status}" + (f" ({stop_reason})" if stop_reason else ""))
    print(f"상한 기준 사용량 {budget.used_upper} / 상한 {args.max_calls or '없음'} · 생성 호출 {budget.generation_calls} · Qwen {budget.qwen_calls}")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return {"completed": EXIT_OK, "completed_with_errors": EXIT_ABORTED, "stopped_by_budget": EXIT_BUDGET}.get(status, EXIT_ABORTED)


def _compare(args: argparse.Namespace) -> int:
    reports = [load_report(Path(p)) for p in args.reports]
    text = render_compare(reports)
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"compare-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"저장: {out}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.story_eval", description="냉장고·구름섬 스토리 채팅 응답 품질 평가")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="평가 실행(또는 --dry-run으로 예상 호출 수만)")
    run.add_argument("--base-url", default="http://127.0.0.1:8000")
    run.add_argument("--label", help="리포트 이름(기본: 서버 모델명)")
    run.add_argument("--suites", type=lambda v: _csv(v, SUITES), default=list(SUITES), help="quality,intent,behavior")
    run.add_argument("--projects", type=lambda v: _csv(v, PROJECTS), default=list(PROJECTS), help="fridge,cloud")
    run.add_argument("--repeat", type=int, default=1, help="같은 계획 반복 횟수")
    run.add_argument("--max-calls", type=int, help="외부 호출 상한(상한 기준 사용량). 실제 공급자에서는 필수")
    run.add_argument("--dry-run", action="store_true", help="예상 호출 수만 출력하고 서버를 호출하지 않는다")
    run.add_argument("--runs", type=int, default=1, help="dry-run에서 비교할 실행(모델) 수만큼 합계를 곱해 보여 준다")
    run.add_argument("--story-attempts", type=int, default=settings.story_generation_attempts, help="호출 수 계산용 생성 시도 상한(기본: 로컬 설정)")
    run.add_argument("--http-attempts", type=int, default=settings.gemini_http_attempts, help="호출 수 계산용 HTTP 재시도(기본: 로컬 설정)")
    run.add_argument("--qwen", type=_bool, default=settings.fridge_qwen_dialogue_enabled, help="호출 수 계산에 냉장고 Qwen 포함(true/false, 기본: 로컬 설정)")
    run.add_argument("--expect-provider", choices=["gemini", "mock"], help="X-Story-Provider 헤더(기본: 서버 health 공급자)")
    run.add_argument("--database-url", help="서버와 같은 DB URL(기본: backend/.env의 DATABASE_URL)")
    run.add_argument("--no-db", action="store_true", help="DB 메타데이터 없이 실행(시도·위반·의도·토큰 집계 불가)")
    run.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    run.add_argument("--pause", type=float, default=0.0, help="LLM 턴 사이 대기(초, 분당 한도 완화)")
    run.add_argument("--timeout", type=float, default=120.0)

    compare = sub.add_parser("compare", help="두 개 이상 report.json 비교표")
    compare.add_argument("reports", nargs="+")
    compare.add_argument("--out", help="저장할 Markdown 경로(기본: eval_reports/compare-시각.md)")

    args = parser.parse_args(argv)
    if args.command == "compare":
        if len(args.reports) < 2:
            parser.error("비교할 report.json을 2개 이상 지정하세요.")
        return _compare(args)
    if args.repeat < 1 or args.runs < 1:
        parser.error("--repeat, --runs는 1 이상")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
