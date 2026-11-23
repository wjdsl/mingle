"""두 모델을 같은 시간대에 비교한다: 대화 단위로 A, B, A, B 번갈아 실행.

공급자 503처럼 시간대에 따라 달라지는 실패가 한 모델에만 몰리지 않도록, 한 모델을 다 돌린 뒤 다른 모델을 돌리지 않는다.
같은 계획(스위트·작품·입력)의 대화 하나를 A 서버에서 끝낸 다음 곧바로 B 서버에서 진행한다.

기본은 실행기가 서버 두 개를 직접 띄운다(--spawn 기본). 두 서버는 GEMINI_CHAT_MODEL만 다르고 나머지 설정은
같은 값을 환경변수로 명시해 넘기며(backend/.env는 수정하지 않는다), DB 파일과 로그는 실행 폴더 안에서 분리한다.
이미 떠 있는 서버를 쓰려면 --a-url/--a-database-url/--b-url/--b-database-url을 준다.

    python -m scripts.story_eval ab --dry-run --quality-repeat 2
    python -m scripts.story_eval ab --model-a gemini-3.1-flash-lite --model-b gemini-3.5-flash-lite --quality-repeat 2 --max-calls 300
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings
from scripts.story_eval.metrics import http_log_summary, parse_gemini_http_log
from scripts.story_eval.plan import build_plans, estimate_calls, schedule
from scripts.story_eval.report import BACKEND_DIR, finalize_run, render_compare
from scripts.story_eval.runner import Budget, BudgetExceeded, RunAborted, RunState, StoryEvalRunner, TurnMetaReader

EXIT_OK, EXIT_ABORTED, EXIT_USAGE, EXIT_BUDGET = 0, 1, 2, 3
# 두 서버에 똑같이 고정하는 값(사용자 지정 조건): Qwen·시작 점검·시드 끔
FIXED_SERVER_ENV = {"FRIDGE_QWEN_DIALOGUE_ENABLED": "false", "LLM_PROBE_ON_STARTUP": "false", "SEED_ON_STARTUP": "false"}


def slugify(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "run"


def server_env(args: argparse.Namespace, model: str, database_url: str) -> dict[str, str]:
    """서버 한 개에 넘길 환경변수(비밀값 없음). 모델과 DB만 서버마다 다르다."""
    env = {
        "LLM_PROVIDER": args.provider,
        "GEMINI_CHAT_MODEL": model,
        "GEMINI_THINKING_LEVEL": args.thinking_level,
        "STORY_GENERATION_ATTEMPTS": str(args.story_attempts),
        "GEMINI_HTTP_ATTEMPTS": str(args.http_attempts),
        "LLM_TIMEOUT_SECONDS": str(args.llm_timeout),
        **FIXED_SERVER_ENV,
        "DATABASE_URL": database_url,
    }
    if args.gemini_base_url:
        env["GEMINI_BASE_URL"] = args.gemini_base_url
    return env


def public_env(env: dict[str, str]) -> dict[str, str]:
    """리포트에 적는 값: DB 경로는 빼고(서버마다 다른 게 정상) 비교 대상 설정만."""
    return {k: v for k, v in env.items() if k != "DATABASE_URL"}


@dataclass(slots=True)
class Side:
    label: str
    base_url: str
    database_url: str
    env: dict[str, str] = field(default_factory=dict)  # 실행기가 띄운 서버의 설정(외부 서버면 비어 있다)
    process: subprocess.Popen | None = None
    log_path: Path | None = None
    http: httpx.AsyncClient | None = None
    reader: TurnMetaReader | None = None
    runner: StoryEvalRunner | None = None
    budget: Budget | None = None
    state: RunState = field(default_factory=RunState)
    server: dict = field(default_factory=dict)
    status: str = "completed"
    stop_reason: str | None = None


def _port_busy(url: str) -> bool:
    try:
        httpx.get(f"{url}/api/health", timeout=1.0)
        return True
    except httpx.HTTPError:
        return False


def spawn_server(side: Side, port: int, out_dir: Path) -> None:
    """uvicorn 서버를 띄운다. backend/.env는 그대로 읽히고 위 환경변수가 그 위에 덮인다(키는 .env에서)."""
    side.log_path = out_dir / f"server_{slugify(side.label)}.log"
    log = side.log_path.open("w", encoding="utf-8")
    env = {**os.environ, **side.env}
    side.process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def wait_healthy(side: Side, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if side.process is not None and side.process.poll() is not None:
            raise RuntimeError(f"{side.label} 서버가 시작 중 종료됐습니다(로그: {side.log_path}).")
        try:
            return httpx.get(f"{side.base_url}/api/health", timeout=2.0).raise_for_status().json()
        except httpx.HTTPError:
            time.sleep(0.5)
    raise RuntimeError(f"{side.label} 서버가 {timeout:.0f}초 안에 응답하지 않았습니다(로그: {side.log_path}).")


def stop_server(side: Side) -> None:
    if side.process is None or side.process.poll() is not None:
        return
    side.process.terminate()
    try:
        side.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        side.process.kill()


def count_generate_requests(log_path: Path) -> int:
    """서버 로그의 generateContent HTTP 시도 수(상태 줄과 연결 오류 줄). 호출 상한을 실제 요청 수로 센다."""
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return len(parse_gemini_http_log(text.splitlines()))


def server_info(health: dict) -> dict:
    llm = health.get("llm") or {}
    return {"provider": llm.get("provider"), "chat_model": llm.get("chat_model"), "degraded": llm.get("degraded"), "database": health.get("database"), "version": health.get("version")}


def check_servers(sides: list[Side], args: argparse.Namespace) -> str | None:
    """두 서버가 비교 조건에 맞는지. 문제가 있으면 사유 문자열."""
    for side in sides:
        s = side.server
        if s.get("degraded"):
            return f"{side.label} 서버가 degraded(Mock 전환) 상태입니다."
        if args.spawn and s.get("provider") != args.provider:
            return f"{side.label} 서버 공급자({s.get('provider')})가 지정값({args.provider})과 다릅니다."
        if args.spawn and args.provider == "gemini" and s.get("chat_model") != side.env.get("GEMINI_CHAT_MODEL"):
            return f"{side.label} 서버 모델({s.get('chat_model')})이 지정값과 다릅니다."
    if {s.server.get("provider") for s in sides} != {sides[0].server.get("provider")}:
        return "두 서버의 공급자가 다릅니다."
    return None


async def run_alternating(sides: list[Side], plans: list, args: argparse.Namespace, log=print) -> None:
    """대화 단위로 A, B, A, B. 한쪽이 상한·할당량·HTTP 오류로 멈추면 비교가 어긋나지 않게 둘 다 멈춘다."""
    order = schedule(plans, args.repeat, args.quality_repeat)
    for step_no, (plan, repeat, index) in enumerate(order, start=1):
        for side in sides:
            log(f"--- [{step_no}/{len(order)}] {side.label}: {plan.suite}/{plan.project} #{index} r{repeat}")
            try:
                await side.runner.run_conversation(plan, repeat=repeat, index=index, state=side.state)
            except BudgetExceeded as exc:
                side.status, side.stop_reason = "stopped_by_budget", str(exc)
            except RunAborted as exc:
                side.status, side.stop_reason = "aborted", str(exc)
            except httpx.HTTPError as exc:
                side.status, side.stop_reason = "aborted", f"HTTP 오류: {type(exc).__name__}"
            if side.status != "completed":
                for other in sides:
                    if other is not side and other.status == "completed":
                        other.status, other.stop_reason = "stopped_with_pair", f"{side.label} 실행이 멈춰 비교를 맞추려고 함께 멈춤({side.stop_reason})"
                return


async def _main(args: argparse.Namespace) -> int:
    plans, cases = build_plans(args.suites, args.projects)
    estimate = estimate_calls(plans, repeat=args.repeat, quality_repeat=args.quality_repeat, story_attempts=args.story_attempts, http_attempts=args.http_attempts, qwen=False)
    from scripts.story_eval.__main__ import print_estimate

    print_estimate(estimate, 2)
    order = schedule(plans, args.repeat, args.quality_repeat)
    print(f"실행 순서: 대화 {len(order)}개 × 모델 2개를 대화마다 A → B로 번갈아 진행(총 {len(order) * 2}개 대화).")
    if args.dry_run:
        print("dry-run: 서버를 띄우거나 호출하지 않았습니다.")
        return EXIT_OK
    if args.provider != "mock" and args.max_calls is None:
        print("실제 공급자로 실행하려면 --max-calls(모델당 상한)가 필요합니다.")
        return EXIT_USAGE

    started_at = datetime.now().astimezone()
    root = Path(args.out_dir) / f"{started_at.strftime('%Y%m%d-%H%M%S')}_ab_{slugify(args.label_a or args.model_a or 'A')}_vs_{slugify(args.label_b or args.model_b or 'B')}"
    root.mkdir(parents=True, exist_ok=True)
    sides: list[Side] = []
    for key in ("a", "b"):
        model = getattr(args, f"model_{key}")
        label = getattr(args, f"label_{key}") or model or key.upper()
        if args.spawn:
            port = getattr(args, f"port_{key}")
            db = f"sqlite+aiosqlite:///{(root / f'{slugify(label)}.db').resolve().as_posix()}"
            sides.append(Side(label, f"http://127.0.0.1:{port}", db, env=server_env(args, model, db)))
        else:
            sides.append(Side(label, getattr(args, f"{key}_url"), getattr(args, f"{key}_database_url")))
    if sides[0].label == sides[1].label:
        print("두 실행의 라벨이 같습니다. --label-a/--label-b로 구분하세요.")
        return EXIT_USAGE

    try:
        if args.spawn:
            for side, port in zip(sides, (args.port_a, args.port_b)):
                if _port_busy(side.base_url):
                    print(f"포트 {port}에 이미 서버가 있습니다. --port-a/--port-b를 바꾸세요.")
                    return EXIT_USAGE
                spawn_server(side, port, root)
        for side in sides:
            side.server = server_info(wait_healthy(side))
            print(f"{side.label}: provider={side.server['provider']} model={side.server['chat_model']} degraded={side.server['degraded']} url={side.base_url}")
        problem = check_servers(sides, args)
        if problem:
            print(f"비교 조건 불일치: {problem}")
            return EXIT_USAGE
        if args.spawn:
            print("두 서버 공통 설정: " + ", ".join(f"{k}={v}" for k, v in public_env(sides[0].env).items() if k != "GEMINI_CHAT_MODEL"))

        async with httpx.AsyncClient(base_url=sides[0].base_url, timeout=args.timeout) as ha, httpx.AsyncClient(base_url=sides[1].base_url, timeout=args.timeout) as hb:
            for side, http in zip(sides, (ha, hb)):
                side.http = http
                side.reader = TurnMetaReader(side.database_url)
                side.budget = Budget(args.max_calls, args.story_attempts, args.http_attempts, False)
                if args.spawn and args.provider == "gemini" and side.log_path is not None:
                    side.budget.http_counter = (lambda path=side.log_path: count_generate_requests(path))
                side.runner = StoryEvalRunner(http, side.reader, side.budget, expect_provider=args.expect_provider or side.server["provider"], pause=args.pause,
                                              log=lambda msg, label=side.label: print(f"  {label} {msg}"))
            try:
                await run_alternating(sides, plans, args)
            finally:
                for side in sides:
                    await side.reader.close()
    finally:
        for side in sides:
            stop_server(side)
    finished_at = datetime.now().astimezone()

    reports = []
    assumed = {"story_generation_attempts": args.story_attempts, "http_attempts": args.http_attempts, "fridge_qwen_dialogue_enabled": False}
    for side in sides:
        http_log = None
        if side.log_path and side.log_path.exists() and args.provider == "gemini":
            tz = finished_at.strftime("%z")
            http_log = http_log_summary(parse_gemini_http_log(side.log_path.read_text(encoding="utf-8").splitlines(), f"{tz[:3]}:{tz[3:]}"))
        report, paths = finalize_run(
            label=side.label, base_url=side.base_url, suites=args.suites, projects=args.projects, repeat=args.repeat, quality_repeat=args.quality_repeat,
            started=started_at, finished=finished_at, status=side.status, stop_reason=side.stop_reason, state=side.state, cases=cases,
            server=side.server, assumed=assumed, budget=side.budget.as_dict(), estimate=estimate, db_metadata=True,
            out_dir=root / slugify(side.label), server_env=public_env(side.env) if side.env else None, http_log=http_log,
        )
        reports.append(report)
        print(f"{side.label}: 상태 {report['run']['status']}" + (f" ({side.stop_reason})" if side.stop_reason else ""))
        print(f"  상한 기준 사용량 {side.budget.used_upper} / {args.max_calls or '없음'} · 생성 호출 {side.budget.generation_calls}")
        for name, path in paths.items():
            print(f"  {name}: {path}")
    compare_path = root / "compare.md"
    compare_path.write_text(render_compare(reports), encoding="utf-8")
    print(f"비교표: {compare_path}")
    statuses = {r["run"]["status"] for r in reports}
    if statuses <= {"completed"}:
        return EXIT_OK
    if "stopped_by_budget" in statuses:
        return EXIT_BUDGET
    return EXIT_ABORTED


def add_parser(sub, add_plan_args) -> None:
    ab = sub.add_parser("ab", help="두 모델을 대화 단위로 번갈아 실행하고 비교표를 만든다")
    add_plan_args(ab)
    ab.add_argument("--model-a", default=settings.gemini_chat_model, help="A 서버 GEMINI_CHAT_MODEL(기본: backend/.env 값)")
    ab.add_argument("--model-b", help="B 서버 GEMINI_CHAT_MODEL")
    ab.add_argument("--label-a", help="A 리포트 이름(기본: 모델명)")
    ab.add_argument("--label-b", help="B 리포트 이름(기본: 모델명)")
    ab.add_argument("--max-calls", type=int, help="모델당 외부 호출 상한(상한 기준 사용량). 실제 공급자에서는 필수")
    ab.add_argument("--dry-run", action="store_true", help="예상 호출 수와 실행 순서만 출력")
    ab.add_argument("--expect-provider", choices=["gemini", "mock"], help="X-Story-Provider 헤더(기본: 서버 health 공급자)")
    spawn = ab.add_argument_group("서버 자동 실행(기본)")
    spawn.add_argument("--port-a", type=int, default=8101)
    spawn.add_argument("--port-b", type=int, default=8102)
    spawn.add_argument("--provider", choices=["gemini", "mock"], default="gemini", help="두 서버의 LLM_PROVIDER")
    spawn.add_argument("--thinking-level", default=settings.gemini_thinking_level, help="두 서버의 GEMINI_THINKING_LEVEL(기본: backend/.env 값)")
    spawn.add_argument("--llm-timeout", type=float, default=settings.llm_timeout_seconds, help="두 서버의 LLM_TIMEOUT_SECONDS(기본: backend/.env 값)")
    spawn.add_argument("--gemini-base-url", help="두 서버의 GEMINI_BASE_URL(가짜 Gemini 검증용, 기본: 실제 API)")
    external = ab.add_argument_group("이미 떠 있는 서버 사용(넷 모두 주면 서버를 띄우지 않는다)")
    external.add_argument("--a-url")
    external.add_argument("--a-database-url")
    external.add_argument("--b-url")
    external.add_argument("--b-database-url")


def main(args: argparse.Namespace) -> int:
    externals = [args.a_url, args.a_database_url, args.b_url, args.b_database_url]
    if any(externals) and not all(externals):
        print("외부 서버를 쓰려면 --a-url, --a-database-url, --b-url, --b-database-url을 모두 지정하세요.")
        return EXIT_USAGE
    args.spawn = not any(externals)
    if args.spawn and not args.dry_run and not (args.model_a and args.model_b):
        print("--model-a와 --model-b가 필요합니다.")
        return EXIT_USAGE
    # STORY_GENERATION_ATTEMPTS·GEMINI_HTTP_ATTEMPTS는 호출 수 계산값(--story-attempts/--http-attempts)을 그대로 두 서버에 넘긴다.
    return asyncio.run(_main(args))
