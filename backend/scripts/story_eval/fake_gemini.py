"""평가 실행기 개발·검증용 가짜 Gemini REST 서버(실제 API 아님, 표준 라이브러리만 사용).

서버를 GEMINI_BASE_URL=http://127.0.0.1:<port>/v1beta, GEMINI_API_KEY=fake 로 띄우면 스토리 턴이 Gemini 경로
(응답 제어·교정 재시도·고정 대사 대체·intent_id·토큰 기록)를 그대로 거친다. 응답은 결정적이다.

- 장면 프롬프트의 의도 ID 목록에서 입력 문장 해시로 하나를 고른다(정확도는 의미 없음, 집계 확인용).
- 입력 해시 % violation_every == 0 이면 첫 시도에 존댓말 문장을 넣어 style_polite 교정 재시도를 만든다.
- 입력 해시 % fail_every == 0 이면 두 시도 모두 JSON이 아닌 응답을 내 고정 대사 대체(fallback)를 만든다.
- usageMetadata에 입력·출력·생각 토큰 수를 넣는다.

    python -m scripts.story_eval.fake_gemini --port 8023
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INTENT = re.compile(r"\[((?:fridge|cloud)_t\d\d_i\d\d)\]")
CORRECTION = "직전 응답 문제"
_counter = itertools.count(1)


FRIDGE_A = ("흠흠, 그렇군.", "이 몸이 보기에 수상하네.", "자네 말에도 일리는 있지.", "허, 배짱 한번 좋군.", "좋네, 일단 두고 보세.", "쯧, 냉기부터 지키게.", "무슨 소리인가, 이 사람아.", "나쁘지 않은 판단일세.", "어허, 서두르지 말게.", "그래, 그 정도면 됐네.", "뭐라? 다시 말해 보게.", "음, 자네답군.")
FRIDGE_B = ("문단속은 철저히 하게.", "오늘 일은 장부에 적어 두지.", "이 몸의 촉은 틀린 적이 없네.", "내일 아침에 다시 이야기하세.", "달걀은 맨 위 칸에 두게.", "전기요금 걱정은 접어 두게.", "창밖 소리에 귀를 기울이게.", "라면은 오늘까지만일세.", "손님이 오면 나부터 부르게.", "밤공기가 꽤 차갑군.", "자네 표정이 한결 낫군.", "서랍 속 영수증을 챙기게.")
CLOUD_A = ("좋아, 바로 간다!", "엔진 소리 괜찮아.", "다들 꽉 잡아!", "바람이 방향을 바꿨어.", "밧줄 하나 더 가져와!", "등불을 앞으로 비춰!", "이쪽 길이 더 빨라.", "흔들려도 침착하게!", "연료는 아직 충분해.", "구름이 갈라지고 있어!", "내가 먼저 건너볼게.", "준비됐으면 출발이야!")
CLOUD_B = ("나도 같이 갈게.", "계기판 숫자 확인했어.", "무서우면 손 잡아.", "로켓은 아직 누르지 마!", "돛 줄 다시 묶을게.", "저기 주민이 손 흔들어.", "속도 조금만 줄이자.", "갑판 미끄러우니 조심해.", "지도에 표시해 둘게.", "다음 구름까지 금방이야.", "내 계산이 맞았어.", "배가 다시 떠올랐어!")


def _hash(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _texts(body: dict) -> tuple[str, str]:
    """(전체 프롬프트 문자열, 마지막 사용자 메시지)."""
    parts = [p.get("text", "") for p in (body.get("systemInstruction") or {}).get("parts", [])]
    last_user = ""
    for content in body.get("contents") or []:
        text = "".join(p.get("text", "") for p in content.get("parts", []))
        parts.append(text)
        if content.get("role") == "user":
            last_user = text
    return "\n".join(parts), last_user


def story_reply(body: dict, *, violation_every: int, fail_every: int) -> str:
    schema = (body.get("generationConfig") or {}).get("responseJsonSchema")
    prompt, last_user = _texts(body)
    if not schema:
        return "pong"
    speakers = schema["properties"]["lines"]["items"]["properties"]["speaker"]["enum"]
    key = _hash(last_user.rsplit("직전 응답 문제", 1)[0])
    if fail_every and key % fail_every == 0:
        return "이건 JSON이 아니다"
    corrected = CORRECTION in last_user or CORRECTION in prompt[-400:]
    polite = bool(violation_every) and key % violation_every == 0 and not corrected
    n = next(_counter)
    intents = list(dict.fromkeys(INTENT.findall(prompt)))
    # 서버의 반복 검사(이전 응답과 90% 이상 같으면 위반)를 피하도록 서로 다른 문장을 고른다.
    if len(speakers) == 1:
        text = f"{FRIDGE_A[n % len(FRIDGE_A)]} {FRIDGE_B[(n * 5 + key) % len(FRIDGE_B)]}" + (" 알겠어요." if polite else "")
        lines = [{"speaker": speakers[0], "text": text}]
    else:
        pool = [s for s in speakers if s != "두두"] or speakers
        first, second = pool[key % len(pool)], pool[(key // 7 + 1) % len(pool)]
        lines = [{"speaker": first, "text": CLOUD_A[n % len(CLOUD_A)] + (" 고마워요." if polite else "")}]
        if second != first:
            lines.append({"speaker": second, "text": CLOUD_B[(n * 5 + key) % len(CLOUD_B)]})
    data = {"lines": lines, "reaction": "고개를 끄덕인다"}
    if intents:
        data["intent_id"] = intents[key % len(intents)]
    return json.dumps(data, ensure_ascii=False)


class Handler(BaseHTTPRequestHandler):
    violation_every = 4
    fail_every = 13
    status = 200

    def log_message(self, *args) -> None:  # 요청 본문을 출력하지 않는다
        pass

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # 모델 메타데이터
        self._send(200, {"name": self.path.rsplit("/", 1)[-1], "supportedGenerationMethods": ["generateContent"]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith(":batchEmbedContents"):
            self._send(200, {"embeddings": [{"values": [0.1] * 8} for _ in body.get("requests", [])]})
            return
        if self.path.endswith(":embedContent"):
            self._send(200, {"embedding": {"values": [0.1] * 8}})
            return
        if self.status != 200:
            self._send(self.status, {"error": {"code": self.status, "status": "UNAVAILABLE", "message": "fake"}})
            return
        text = story_reply(body, violation_every=self.violation_every, fail_every=self.fail_every)
        self._send(
            200,
            {
                "candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": len(json.dumps(body)) // 3, "candidatesTokenCount": len(text) // 2, "thoughtsTokenCount": 11},
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="평가 실행기 검증용 가짜 Gemini 서버")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8023)
    parser.add_argument("--violation-every", type=int, default=4, help="0이면 위반 없음")
    parser.add_argument("--fail-every", type=int, default=13, help="0이면 대체 응답 없음")
    parser.add_argument("--status", type=int, default=200, help="생성 요청에 돌려줄 HTTP 상태(503 등 실패 재현)")
    args = parser.parse_args()
    Handler.violation_every, Handler.fail_every, Handler.status = args.violation_every, args.fail_every, args.status
    print(f"fake gemini on http://{args.host}:{args.port}/v1beta (실제 API 아님)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
