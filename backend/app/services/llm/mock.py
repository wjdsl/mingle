"""오프라인/테스트용 LLM.

- API 키가 없어도 전체 대화·RAG·기억·트리거 흐름을 검증할 수 있게 한다.
- 임베딩은 문자 bigram feature hashing 으로 만들어 한국어에서도 어느 정도
  어휘 기반 검색이 동작한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator

from app.services.llm.base import LLMProvider, LLMResult, fit_embedding

_HANGUL_WORD = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d{2,}")


class MockProvider(LLMProvider):
    name = "mock"
    chat_model = "mock-persona-v1"

    def __init__(self, embedding_dim: int) -> None:
        self.embedding_dim = embedding_dim

    # ------------------------------------------------------------------ #
    # 대화 생성
    # ------------------------------------------------------------------ #
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        started = time.perf_counter()
        if json_mode:
            text = json.dumps({"notes": []}, ensure_ascii=False)
        else:
            text = self._compose(messages)
        latency = int((time.perf_counter() - started) * 1000)
        return LLMResult(
            text=text,
            provider=self.name,
            model=self.chat_model,
            latency_ms=latency,
            prompt_tokens=sum(len(m["content"]) for m in messages) // 2,
            completion_tokens=len(text) // 2,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        text = self._compose(messages)
        step = 14
        for index in range(0, len(text), step):
            yield text[index : index + step]
            await asyncio.sleep(0)

    # ------------------------------------------------------------------ #
    # 임베딩
    # ------------------------------------------------------------------ #
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.embedding_dim
        for token in self._tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.embedding_dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return fit_embedding(vector, self.embedding_dim)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        lowered = text.lower()
        words = _HANGUL_WORD.findall(lowered)
        bigrams: list[str] = []
        for word in _HANGUL_WORD.findall(lowered):
            if len(word) >= 2:
                bigrams.extend(word[i : i + 2] for i in range(len(word) - 1))
        return words + bigrams

    # ------------------------------------------------------------------ #
    # 프롬프트 해석 → 페르소나풍 응답
    # ------------------------------------------------------------------ #
    def _compose(self, messages: list[dict[str, str]]) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_text = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        ).strip()

        name = self._grab(r"-\s*이름:\s*(.+)", system) or "그대의 친구"
        stage = self._grab(r"현재 관계 단계:\s*(.+)", system) or "낯섦"
        refs = self._references(system)
        notes = self._notes(system)

        opener = self._pick(
            user_text + stage,
            [
                "음, 그렇게 말해주니 마음이 조금 놓이는군.",
                "그대의 목소리를 들으니 이 밤이 조금 덜 길게 느껴지는걸.",
                "잠시만, 그 말을 마음에 새겨두고 싶어.",
                "후후, 그런 이야기는 나도 처음 들어보는걸.",
            ],
        )
        memory_line = ""
        if notes:
            memory_line = f" 그리고 {notes[0]}라고 했던 것도 기억하고 있어."
        elif stage in ("친밀", "각별"):
            memory_line = " 우리가 나눈 이야기들은 하나도 잊지 않았어."

        reference_line = ""
        if refs:
            reference_line = f" {refs[0]}"

        body = self._pick(
            user_text,
            [
                "그 마음이 어떤 색인지 조금 더 들려줄 수 있겠나?",
                "나는 그대가 어떤 선택을 하든, 그 옆에 있어주고 싶어.",
                "이야기가 흘러가는 대로 따라가 보자. 때로는 그게 가장 좋은 길이니까.",
                "그대와 이렇게 마주 앉아 있는 시간은 늘 짧게 느껴져.",
            ],
        )

        if stage in ("친밀", "각별"):
            closer = "…조금만 더 곁에 있어도 될까?"
        elif stage == "호기심":
            closer = "다음에는 무엇을 이야기해볼까?"
        else:
            closer = "천천히, 서두르지 않아도 괜찮아."

        user_echo = self._summarize(user_text)
        return f"{opener} {user_echo}{reference_line}{memory_line} {body} {closer}".strip()

    @staticmethod
    def _grab(pattern: str, text: str) -> str:
        match = re.search(pattern, text)
        return match.group(1).strip() if match else ""

    def _references(self, system: str) -> list[str]:
        section = system.split("### 검색된 참고 자료", 1)
        if len(section) < 2:
            return []
        refs: list[str] = []
        for line in section[1].splitlines():
            line = line.strip()
            if line.startswith("- "):
                content = re.sub(r"^-\s*\[[^\]]+\]\s*", "", line)
                refs.append(content.strip())
        return refs[:2]

    def _notes(self, system: str) -> list[str]:
        section = system.split("### 사용자 기억", 1)
        if len(section) < 2:
            return []
        notes: list[str] = []
        for line in section[1].splitlines():
            if line.strip().startswith("- "):
                notes.append(line.strip()[2:])
            if len(notes) >= 3:
                break
        return notes

    @staticmethod
    def _summarize(text: str) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) > 60:
            cleaned = cleaned[:60] + "…"
        if not cleaned:
            return ""
        return f"'{cleaned}'라니, "

    @staticmethod
    def _pick(seed: str, options: list[str]) -> str:
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
        return options[int(digest[:8], 16) % len(options)]
