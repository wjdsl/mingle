"""Qwen(Colab) 연결 상태 확인: python -m scripts.check_qwen

QWEN_API_URL/QWEN_API_KEY(backend/.env 또는 환경변수)로 /health 와 /generate 를 1회씩 호출하고,
응답 모델명이 실제 Qwen인지 출력한다. Mock 응답은 성공으로 보지 않는다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.llm import LLMError  # noqa: E402
from app.services.llm.qwen_provider import QwenProvider  # noqa: E402


async def main() -> int:
    if not settings.qwen_api_url or not settings.qwen_api_key:
        print("QWEN_API_URL / QWEN_API_KEY 가 설정되지 않았습니다.")
        return 2
    try:
        provider = QwenProvider(
            base_url=settings.qwen_api_url,
            api_key=settings.qwen_api_key,
            timeout=settings.qwen_timeout_seconds,
        )
    except ValueError as exc:
        print(f"설정 오류: {exc}")
        return 2
    try:
        health = await provider._client.get("/health")
        print(f"GET /health -> HTTP {health.status_code}")
        if health.headers.get("ngrok-error-code") == "ERR_NGROK_3200" or (
            health.status_code == 404 and "ERR_NGROK_3200" in health.text
        ):
            print("ngrok 터널이 오프라인입니다 (ERR_NGROK_3200). Colab에서 추론 서버와 터널을 다시 시작하세요.")
            return 1
        result = await provider.generate([{"role": "user", "content": "안녕"}], max_tokens=30)
        print(f"POST /generate -> provider={result.provider} model={result.model} "
              f"latency={result.latency_ms}ms")
        return 0
    except (LLMError, httpx.HTTPError) as exc:
        print(f"실패: {exc}")
        return 1
    finally:
        await provider.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
