"""실행 중인 API 서버 대상 라이브 스모크 테스트.

한 번의 실행으로 다음 흐름을 모두 검증한다.

1. 비회원 세션 생성 (개인 코드 발급)
2. SSE 스트리밍 대화 3턴 (RAG 인용 / User Note / 스토리 이벤트)
3. 3턴째 메시지로 Marketing Trigger + CTA 노출
4. CTA 클릭 이벤트 기록
5. 개인 코드로 세션 복구
6. 관리자 로그인 후 B2B Dashboard 집계 확인

사용 예:
    python scripts/smoke_live.py
    python scripts/smoke_live.py --base-url http://127.0.0.1:8000
    python scripts/smoke_live.py --persona kai-orbital7

주의:
    - 실제 LLM(Gemini/OpenAI)을 호출하므로 과금이 발생할 수 있다.
    - .env 의 ADMIN_EMAIL / ADMIN_PASSWORD 를 사용한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MESSAGES = [
    "안녕! 오늘 밤 하늘 이야기 들려줄래?",
    "너는 어떤 곳에 살아? 별의 회랑이 궁금해.",
    "너 관련 굿즈나 선물 같은 게 있으면 알려줄래?",
]

BASE_URL = "http://127.0.0.1:8000"


def load_env_defaults() -> None:
    """backend/.env 가 있으면 관리자 계정 값을 읽어 온다."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request(
    method: str,
    path: str,
    payload: dict | None = None,
    headers: dict | None = None,
):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        return urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"[FAIL] {method} {path} -> {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"[FAIL] 서버에 연결할 수 없습니다: {BASE_URL}\n"
            f"        uvicorn app.main:app --reload 로 서버를 먼저 실행해 주세요.\n{exc}"
        ) from exc


def get_json(method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    with request(method, path, payload, headers) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_stream(code: str, conversation_id: str, message: str) -> dict:
    """SSE 응답을 읽어 final 이벤트(ChatResponse)를 반환한다."""
    final: dict | None = None
    event = ""
    tokens: list[str] = []

    with request(
        "POST",
        "/api/chat/stream",
        {"conversation_id": conversation_id, "message": message},
        {"X-Personal-Code": code},
    ) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                continue
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                if event == "token":
                    tokens.append(data.get("token", ""))
                elif event == "final":
                    final = data
                elif event == "error":
                    raise SystemExit(f"[FAIL] 스트리밍 오류: {data.get('detail')}")

    if final is None:
        raise SystemExit("[FAIL] final 이벤트를 받지 못했습니다.")
    final["_streamed_chars"] = len("".join(tokens))
    return final


def print_turn(index: int, message: str, result: dict) -> None:
    state = result["state"]
    print(f"\n[{index}턴] 나: {message}")
    reply = result["reply"].replace("\n", " ")
    print(f"  {result['provider']} · {result['latency_ms']}ms · 스트리밍 {result['_streamed_chars']}자")
    print(f"  {reply[:160]}{'...' if len(reply) > 160 else ''}")
    print(
        f"  상태: {state['stage']} / 턴 {state['turn_count']} / "
        f"호감 {state['affinity']} / 신뢰 {state['trust']} / 챕터 {state['chapter']}"
    )
    if result["sources"]:
        for source in result["sources"]:
            print(f"  · RAG 인용: {source['category']} · {source['title']} ({source['score']})")
    if result["story_events"]:
        for story in result["story_events"]:
            print(f"  · 스토리 이벤트: [{story['code']}] {story['title']}")
    if result["notes_updated"]:
        for note in result["notes_updated"]:
            print(f"  · User Note 저장: {note['key']} = {note['value']}")
    if result["triggers"]:
        for trigger in result["triggers"]:
            cta = trigger.get("cta") or {}
            print(
                f"  · 마케팅 트리거: [{trigger['code']}] {trigger['name']} "
                f"→ CTA {cta.get('label', '-')}"
            )
    if result["ending"]:
        print(f"  · 엔딩 도달: [{result['ending']['code']}] {result['ending']['title']}")


def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser(description="Persona Companion AI 라이브 스모크 테스트")
    parser.add_argument("--base-url", default=os.environ.get("SMOKE_BASE_URL", BASE_URL))
    parser.add_argument("--persona", default="seo-harin")
    parser.add_argument("--display-name", default="스모크테스터")
    parser.add_argument(
        "--messages",
        nargs="*",
        default=DEFAULT_MESSAGES,
        help="전송할 사용자 메시지 목록 (기본 3턴)",
    )
    parser.add_argument("--admin-email", default=None)
    parser.add_argument("--admin-password", default=None)
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")
    load_env_defaults()

    print(f"=== 대상 서버: {BASE_URL} ===")
    health = get_json("GET", "/api/health")
    print(
        f"health: {health['status']} · DB {health['database']} · "
        f"LLM {health['llm']['provider']}/{health['llm']['chat_model']} · "
        f"degraded={health['llm']['degraded']}"
    )

    # 1) 세션 생성
    created = get_json(
        "POST",
        "/api/sessions",
        {"persona_slug": args.persona, "display_name": args.display_name},
    )
    code = created["personal_code"]
    conversation_id = created["conversation"]["id"]
    print(f"\n세션 생성 완료 · 개인 코드 {code} · 대화 {conversation_id}")

    # 2) 대화 진행
    triggers: list[dict] = []
    for index, message in enumerate(args.messages, start=1):
        result = chat_stream(code, conversation_id, message)
        print_turn(index, message, result)
        if result["triggers"]:
            triggers = result["triggers"]

    # 3) CTA 클릭 추적
    clicked = None
    for trigger in triggers:
        cta = trigger.get("cta")
        if not cta:
            continue
        clicked = get_json(
            "POST",
            "/api/marketing/events",
            {
                "conversation_id": conversation_id,
                "cta_id": cta["id"],
                "metadata": {"source": "smoke_live", "trigger_code": trigger["code"]},
            },
            {"X-Personal-Code": code},
        )
        print(f"\nCTA 클릭 기록: {cta['label']} ({clicked['event_type']})")
        break
    if clicked is None:
        print("\n[안내] 이번 대화에서는 CTA가 노출되지 않았습니다. --messages 로 3턴 이상 보내 보세요.")

    # 4) 개인 코드로 복구
    resumed = get_json("POST", "/api/sessions/resume", {"personal_code": code})
    print(
        f"세션 복구 성공: 대화 {len(resumed['conversations'])}개 · "
        f"최근 상태 {resumed['conversation']['stage'] if resumed['conversation'] else '-'}"
    )

    # 5) 관리자 대시보드
    email = args.admin_email or os.environ.get("ADMIN_EMAIL", "admin@companion.ai")
    password = args.admin_password or os.environ.get("ADMIN_PASSWORD", "admin1234!")
    token = get_json(
        "POST", "/api/admin/login", {"email": email, "password": password}
    )["access_token"]
    overview = get_json(
        "GET", "/api/admin/overview?days=14", headers={"Authorization": f"Bearer {token}"}
    )
    totals = overview["totals"]
    print("\n=== B2B Dashboard ===")
    print(
        f"세션 {totals['sessions']} · 대화 {totals['conversations']} · "
        f"완결 {totals['completed_conversations']} · 메시지 {totals['messages']} · "
        f"평균 지연 {totals['avg_latency_ms']}ms"
    )
    print(
        f"트리거 노출 {totals['trigger_impressions']} / 클릭 {totals['trigger_clicks']} "
        f"/ CTR {totals['ctr']}%"
    )
    for trigger in overview["triggers"]:
        if trigger["impressions"] or trigger["clicks"]:
            print(
                f"  · {trigger['persona_name']} / {trigger['name']}: "
                f"노출 {trigger['impressions']} · 클릭 {trigger['clicks']} · CTR {trigger['ctr']}%"
            )

    print("\n모든 단계 통과 ✅")


if __name__ == "__main__":
    main()
