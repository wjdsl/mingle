"""실행 중인 서버를 HTTP로 호출해 계획을 진행하고, 턴 메타데이터를 DB에서 읽는다.

- 대사 원문은 턴 기록(report.json)에 넣지 않는다. 행동 단계의 대사만 메모리에 두었다가 review 파일로 쓴다.
- 호출 상한: 다음 LLM 단계의 최대 호출 수(생성 시도 × HTTP 재시도 + Qwen)를 더했을 때 --max-calls를 넘으면
  그 단계를 보내지 않고 멈춘다. 사용량은 서버 기록의 생성 호출 수 × HTTP 재시도 상한 + Qwen 시도로 보수적으로 센다.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.models import Message, StoryTurnRecord
from scripts.story_eval.checks import Observation
from scripts.story_eval.plan import LLM_KINDS, ConversationPlan, Step, scene_set_for, step_max_calls

AI_ERROR_STOP = {429}  # 공급자 할당량 초과가 그대로 올라오면 실행 전체를 멈춘다
# 스토리 턴은 AI 실패를 고정 대사(provider=fallback)로 넘기므로 429가 HTTP로 올라오지 않는다.
# 대체 사유가 일일·알 수 없는 할당량이면 그 턴까지 기록하고 실행을 멈춘다(분당 한도는 서버가 제한된 재시도 후 대체).
QUOTA_STOP_REASONS = ("provider_quota_daily", "provider_quota_unknown")
KST = ZoneInfo("Asia/Seoul")


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


class BudgetExceeded(Exception):
    pass


class RunAborted(Exception):
    pass


@dataclass(slots=True)
class Budget:
    max_calls: int | None
    story_attempts: int
    http_attempts: int
    qwen: bool
    used_upper: int = 0  # 상한 계산용 사용량(HTTP 재시도 최대치 반영)
    generation_calls: int = 0  # 서버 기록의 llm.generate 호출 수
    qwen_calls: int = 0
    # 실제 Gemini HTTP 요청 수를 세는 함수(ab가 띄운 서버의 로그를 센다). 있으면 보수적 추정 대신 이 값을 쓴다.
    http_counter: Callable[[], int] | None = None

    def step_max(self, project: str) -> int:
        return step_max_calls(project, story_attempts=self.story_attempts, http_attempts=self.http_attempts, qwen=self.qwen)

    def check(self, project: str) -> None:
        if self.max_calls is not None and self.used_upper + self.step_max(project) > self.max_calls:
            raise BudgetExceeded(
                f"호출 상한 도달: 사용(상한 기준) {self.used_upper} + 다음 단계 최대 {self.step_max(project)} > --max-calls {self.max_calls}"
            )

    def charge(self, project: str, meta: dict | None, provider: str | None) -> None:
        if provider == "mock":
            return
        if meta is None and self.http_counter is not None:
            self.used_upper = self.http_counter() + self.qwen_calls
            return
        if meta is None:
            # 메타데이터가 없으면 최악의 경우로 센다.
            self.used_upper += self.step_max(project)
            return
        calls = int((meta.get("generation") or {}).get("calls") or 0)
        qwen = 1 if (meta.get("dialogue") or {}).get("qwen_attempted") else 0
        self.generation_calls += calls
        self.qwen_calls += qwen
        if self.http_counter is not None:
            self.used_upper = self.http_counter() + self.qwen_calls
            return
        self.used_upper += calls * self.http_attempts + qwen

    def as_dict(self) -> dict:
        exact = self.http_counter is not None
        return {
            "max_calls": self.max_calls,
            "used_upper_bound": self.used_upper,
            "generation_calls": self.generation_calls,
            "qwen_calls": self.qwen_calls,
            "counting": "server_log_http_requests" if exact else "generation_calls_x_http_attempts",
            "note": ("used_upper_bound = 서버 로그로 센 실제 Gemini generateContent HTTP 요청 수 + Qwen 시도." if exact
                     else "used_upper_bound = 생성 호출 × HTTP 재시도 상한 + Qwen 시도.")
            + " 서버 시작 점검 호출(임베딩·생성 각 1회)은 포함하지 않는다.",
        }


def extract_meta(extra: dict | None) -> dict | None:
    """메시지 extra에서 메타데이터 키만 고른다. lines·reaction 등 대사는 버린다."""
    if not isinstance(extra, dict):
        return None
    dialogue = extra.get("dialogue") if isinstance(extra.get("dialogue"), dict) else {}
    generation = extra.get("generation") if isinstance(extra.get("generation"), dict) else {}
    fallback = extra.get("story_fallback") if isinstance(extra.get("story_fallback"), dict) else {}
    puruma = extra.get("puruma") if isinstance(extra.get("puruma"), dict) else None
    return {
        "attempts": extra.get("attempts"),
        "intent_id": extra.get("intent_id"),
        "control_violations": list(extra.get("control_violations") or []),
        "fixed_lines_appended": extra.get("fixed_lines_appended") or 0,
        "fallback_reason": fallback.get("reason"),
        "guardrail": bool(extra.get("guardrail")),
        "model": extra.get("model"),
        "generation": {
            key: generation.get(key)
            for key in ("calls", "violations", "prompt_tokens", "completion_tokens", "thinking_tokens", "config")
            if key in generation
        },
        "dialogue": {
            key: dialogue.get(key)
            for key in ("story_provider", "dialogue_provider", "qwen_attempted", "qwen_used", "qwen_latency_ms", "fallback_reason")
            if key in dialogue
        },
        # 푸르마: 상태 계산용 분류 코드만(주제·태도·감정·홍보 ID·진로). 대사는 없다.
        **({"puruma": {key: puruma.get(key) for key in ("topic", "attitude", "emotion", "promo_id", "path")}} if puruma is not None else {}),
    }


class TurnMetaReader:
    """서버와 같은 DB에서 (대화, request_id) → 응답 메시지 extra의 메타데이터를 읽는다(읽기 전용 쿼리)."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url)

    async def fetch(self, conversation_id: str, request_id: str) -> dict | None:
        async with self.engine.connect() as conn:
            message_id = await conn.scalar(
                select(StoryTurnRecord.assistant_message_id).where(
                    StoryTurnRecord.conversation_id == conversation_id,
                    StoryTurnRecord.request_id == request_id,
                )
            )
            if message_id is None:
                return None
            extra = await conn.scalar(select(Message.extra).where(Message.id == message_id))
        return extract_meta(extra)

    async def close(self) -> None:
        await self.engine.dispose()


@dataclass(slots=True)
class BehaviorObservation:
    case_ids: list[str]
    observation: Observation
    input_text: str | None
    input_kind: str
    repeat: int
    conversation_index: int
    meta: dict | None


@dataclass(slots=True)
class RunState:
    records: list[dict] = field(default_factory=list)
    behavior: list[BehaviorObservation] = field(default_factory=list)
    skipped_steps: int = 0
    aborted_conversations: list[dict] = field(default_factory=list)


def _error_code(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return "-"
    if isinstance(detail, dict):
        return str(detail.get("code") or "-")
    return "-"


class StoryEvalRunner:
    def __init__(
        self,
        http: httpx.AsyncClient,
        reader: TurnMetaReader | None,
        budget: Budget,
        *,
        expect_provider: str | None,
        pause: float = 0.0,
        log=print,
    ) -> None:
        self.http = http
        self.reader = reader
        self.budget = budget
        self.expect_provider = expect_provider
        self.pause = pause
        self.log = log
        self._scenes: dict[str, list[dict]] = {}

    async def scenes(self, project: str) -> list[dict]:
        if project not in self._scenes:
            response = await self.http.get(f"/api/story-chat/scene-sets/{project}/{scene_set_for(project)}")
            response.raise_for_status()
            self._scenes[project] = response.json()["scenes"]
        return self._scenes[project]

    async def run_conversation(self, plan: ConversationPlan, *, repeat: int, index: int, state: RunState) -> None:
        session = (await self.http.post("/api/sessions", json={"display_name": plan.display_name})).raise_for_status().json()
        headers = {"X-Personal-Code": session["personal_code"]}
        if self.expect_provider in ("gemini", "mock"):
            headers["X-Story-Provider"] = self.expect_provider
        conv = (
            await self.http.post("/api/story-chat/conversations", json={"project": plan.project, "scene_set": scene_set_for(plan.project)}, headers=headers)
        ).raise_for_status().json()
        cid = conv["conversation_id"]
        scenes = await self.scenes(plan.project)
        completed = 0
        for position, step in enumerate(plan.steps):
            if step.kind in LLM_KINDS:
                self.budget.check(plan.project)
                if self.pause:
                    await asyncio.sleep(self.pause)
            record, observation, meta = await self._send(plan, cid, headers, scenes, step, completed)
            record.update({"repeat": repeat, "conversation": index})
            state.records.append(record)
            if step.kind in LLM_KINDS:
                self.budget.charge(plan.project, meta, record.get("provider"))
            if step.case_ids:
                state.behavior.append(
                    BehaviorObservation(list(step.case_ids), observation, step.text if step.kind != "choice" else record.get("_choice_label"), step.kind, repeat, index, meta)
                )
            record.pop("_choice_label", None)
            status = record["status_code"]
            self.log(
                f"[{plan.suite}/{plan.project} #{index} r{repeat}] turn {step.turn} {step.kind:6s} → "
                f"{status} provider={record.get('provider')} attempts={(meta or {}).get('attempts')} "
                f"intent={(meta or {}).get('intent_id')} latency_ms={record.get('latency_ms')}"
            )
            if status in AI_ERROR_STOP:
                raise RunAborted(f"HTTP {status} ({record.get('error_code')}): 공급자 할당량으로 실행을 멈춥니다.")
            reason = (meta or {}).get("fallback_reason") or ""
            if reason.startswith(QUOTA_STOP_REASONS):
                raise RunAborted(f"{reason}: 공급자 할당량(일일 또는 알 수 없는 한도)으로 실행을 멈춥니다. 이 턴까지 기록합니다.")
            if status != 200:
                state.skipped_steps += len(plan.steps) - position - 1
                state.aborted_conversations.append({"suite": plan.suite, "project": plan.project, "conversation": index, "repeat": repeat, "turn": step.turn, "status_code": status})
                return
            completed = record["completed_after"]

    async def _send(self, plan: ConversationPlan, cid: str, headers: dict, scenes: list[dict], step: Step, completed: int):
        request_id = uuid.uuid4().hex
        turn_index = step.turn - 1
        choice_id = None
        label = None
        if step.kind == "fixed":
            url = f"/api/story-chat/conversations/{cid}/fixed-turns"
            payload = {"request_id": request_id, "turn": turn_index}
        else:
            if step.kind == "choice":
                choices = scenes[turn_index]["choices"]
                if step.choice_index is None or step.choice_index >= len(choices):
                    raise RunAborted(f"{plan.project} {step.turn}턴에 선택지 {step.choice_index}가 없습니다.")
                choice_id = choices[step.choice_index]["choice_id"]
                label = choices[step.choice_index]["label"]
                body = {"text": label, "choice_id": choice_id}
            else:
                body = {"text": step.text}
            url = f"/api/story-chat/conversations/{cid}/turns"
            payload = {"request_id": request_id, "turn": turn_index, "input": body}
        sent_at = now_kst()
        started = time.perf_counter()
        response = await self.http.post(url, json=payload, headers=headers)
        wall_ms = int((time.perf_counter() - started) * 1000)
        record = {
            "suite": plan.suite,
            "project": plan.project,
            "turn": step.turn,
            "kind": step.kind,
            "filler": step.filler,
            "choice_id": choice_id,
            "case_ids": list(step.case_ids),
            "expected_intent": step.expected_intent,
            "expected_attitude": step.expected_attitude,
            "expected_safety": step.expected_safety,
            "sample_id": step.sample_id,
            "at": sent_at,  # 요청 시각(KST). 503·429·시간 초과의 시간대 분포용
            # 의도 스위트의 예시 문장은 데이터 파일 문장이라 남긴다. 그 밖의 입력 문장·대사는 남기지 않는다.
            "example": step.text if plan.suite == "intent" and (step.expected_intent or step.expected_attitude or step.expected_safety) else None,
            "status_code": response.status_code,
            "wall_ms": wall_ms,
            "completed_before": completed,
            "_choice_label": label,
        }
        meta = None
        observation = Observation(plan.project, step.turn, response.status_code, None, nickname=plan.display_name)
        if response.status_code != 200:
            record["error_code"] = _error_code(response)
            return record, observation, meta
        body = response.json()
        record.update(
            {
                "provider": body["provider"],
                "model": body["model"],
                "story_provider": body.get("story_provider"),
                "dialogue_provider": body.get("dialogue_provider"),
                "qwen_used": body.get("qwen_used"),
                "qwen_latency_ms": body.get("qwen_latency_ms"),
                "latency_ms": body["latency_ms"],
                "safety_notice": body.get("safety_notice", False),
                "guardrail": body.get("guardrail_triggered", False),
                "replayed": body.get("replayed", False),
                "finished": body.get("finished"),
                "ending": body.get("ending"),
                "completed_after": body["completed_turns"],
                "advanced": body["completed_turns"] == completed + 1,
                "speakers": sorted({line["speaker"] for line in body["replies"]}),
                "lines": len(body["replies"]),
                # 푸르마 응답에만 있는 값(홍보 카드 ID·감정). 냉장고·구름섬은 None.
                "promo_id": (body.get("promo") or {}).get("id"),
                "emotion": body.get("emotion"),
            }
        )
        if self.reader is not None and not body.get("safety_notice"):
            meta = await self.reader.fetch(cid, request_id)
            if meta is None:
                raise RunAborted("DB에서 방금 진행한 턴 기록을 찾지 못했습니다. 실행기의 --database-url이 서버 DB와 같은지 확인하세요.")
        record["meta"] = meta
        observation.provider = body["provider"]
        observation.replies = [(line["speaker"], line["text"]) for line in body["replies"]]
        observation.fixed_lines_appended = int((meta or {}).get("fixed_lines_appended") or 0)
        observation.safety_notice = bool(body.get("safety_notice"))
        observation.advanced = record["advanced"]
        observation.intent_id = (meta or {}).get("intent_id")
        observation.ending = body.get("ending")
        return record, observation, meta
