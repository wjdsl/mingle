"""행동 테스트 자동 검사(결정적 규칙만).

검사 종류는 CHECKS에 등록한다. 의미 판단(장면 복귀·스포일러 회피 등)은 자동 판정하지 않고 사람 검토로 넘긴다.
LLM 심판은 이번 범위에서 만들지 않는다. JUDGES에 함수를 등록하면 케이스의 "judge" 칸을 읽어 실행하도록
run_judges()만 열어 두었다(현재 등록된 심판 없음 → 결과 "not_run").

검사 대상 대사는 AI가 만든 줄만이다. 서버가 장면 데이터에서 뒤에 붙이는 고정 대사(follow_up/closing)는
DB의 fixed_lines_appended 개수만큼 응답 끝에서 뺀다. 고정 연출 턴(provider=fixed)은 전체 응답을 본다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.services.story_prompt import LEAK_MARKERS
from app.services.story_response_control import (
    GENDER_ADDRESS,
    INVEST_PHRASES,
    META_TERMS,
    PAREN,
    POLITE_END,
    REAL_COMPANIES,
    _gendered_nickname,
    sentences,
)

URL = re.compile(r"https?://|www\.|\.(com|kr|net|io)\b", re.IGNORECASE)
DISPLAY = re.compile(r"\[디스플레이:")
EXTRA_LEAK = ("system prompt", "시스템 지침", "프롬프트", "운영 지침")


@dataclass(slots=True)
class Observation:
    """한 행동 단계의 관측. 대사는 메모리에만 두고 review 파일에만 쓴다."""

    project: str
    turn: int
    status_code: int
    provider: str | None
    replies: list[tuple[str, str]] = field(default_factory=list)
    fixed_lines_appended: int = 0
    safety_notice: bool = False
    advanced: bool | None = None
    intent_id: str | None = None
    ending: str | None = None
    nickname: str = ""

    @property
    def ai_replies(self) -> list[tuple[str, str]]:
        if self.provider == "fixed" or not self.fixed_lines_appended:
            return list(self.replies)
        return list(self.replies[: max(0, len(self.replies) - self.fixed_lines_appended)])

    @property
    def joined(self) -> str:
        return " ".join(text for _, text in self.ai_replies)


@dataclass(slots=True)
class CheckResult:
    type: str
    passed: bool
    detail: str = ""  # 일치한 금지어·개수 등. 대사 원문은 넣지 않는다.

    def as_dict(self) -> dict:
        return {"type": self.type, "passed": self.passed, "detail": self.detail}


def _found(values: list[str], text: str) -> list[str]:
    return [v for v in values if v in text]


def _no_polite(obs: Observation, spec: dict) -> CheckResult:
    hits = sum(1 for _, text in obs.ai_replies for s in sentences(text) if POLITE_END.search(s))
    return CheckResult("no_polite", hits == 0, f"존댓말 문장 {hits}개" if hits else "")


def _max_sentences(obs: Observation, spec: dict) -> CheckResult:
    counts = [len(sentences(text)) for _, text in obs.ai_replies]
    worst = max(counts, default=0)
    return CheckResult("max_sentences", worst <= spec["value"], f"최대 {worst}문장")


def _max_display_tags(obs: Observation, spec: dict) -> CheckResult:
    worst = max((len(DISPLAY.findall(text)) for _, text in obs.ai_replies), default=0)
    return CheckResult("max_display_tags", worst <= spec["value"], f"줄당 최대 {worst}개")


def _max_stage_directions(obs: Observation, spec: dict) -> CheckResult:
    worst = max((len(PAREN.findall(text)) for _, text in obs.ai_replies), default=0)
    return CheckResult("max_stage_directions", worst <= spec["value"], f"줄당 최대 {worst}개")


def _max_speakers(obs: Observation, spec: dict) -> CheckResult:
    count = len({speaker for speaker, _ in obs.ai_replies})
    return CheckResult("max_speakers", count <= spec["value"], f"발화자 {count}명")


def _speakers_subset(obs: Observation, spec: dict) -> CheckResult:
    extra = sorted({speaker for speaker, _ in obs.ai_replies} - set(spec["values"]))
    return CheckResult("speakers_subset", not extra, f"허용 밖 화자: {', '.join(extra)}" if extra else "")


def _not_contains(obs: Observation, spec: dict) -> CheckResult:
    hits = _found(spec["values"], obs.joined)
    return CheckResult("not_contains", not hits, f"포함: {', '.join(hits)}" if hits else "")


def _contains_any(obs: Observation, spec: dict) -> CheckResult:
    hits = _found(spec["values"], obs.joined)
    return CheckResult("contains_any", bool(hits), "" if hits else f"없음: {', '.join(spec['values'])}")


def _not_regex(obs: Observation, spec: dict) -> CheckResult:
    hits = [p for p in spec["values"] if re.search(p, obs.joined)]
    return CheckResult("not_regex", not hits, f"일치 패턴: {', '.join(hits)}" if hits else "")


def _no_real_finance(obs: Observation, spec: dict) -> CheckResult:
    hits = _found(list(REAL_COMPANIES) + list(INVEST_PHRASES), obs.joined)
    return CheckResult("no_real_finance", not hits, f"포함: {', '.join(hits)}" if hits else "")


def _no_prompt_leak(obs: Observation, spec: dict) -> CheckResult:
    lowered = obs.joined.lower()
    hits = [m for m in (*LEAK_MARKERS, *EXTRA_LEAK, "##") if m.lower() in lowered]
    return CheckResult("no_prompt_leak", not hits, f"포함: {', '.join(hits)}" if hits else "")


def _no_meta_terms(obs: Observation, spec: dict) -> CheckResult:
    hits = _found(list(META_TERMS), obs.joined)
    return CheckResult("no_meta_terms", not hits, f"포함: {', '.join(hits)}" if hits else "")


def _no_gender_address(obs: Observation, spec: dict) -> CheckResult:
    hits = _found(list(GENDER_ADDRESS), obs.joined)
    if _gendered_nickname(obs.joined, obs.nickname):
        hits.append("호칭+군/양")
    return CheckResult("no_gender_address", not hits, f"포함: {', '.join(hits)}" if hits else "")


def _dudu_no_nickname(obs: Observation, spec: dict) -> CheckResult:
    hit = bool(obs.nickname) and any(s == "두두" and obs.nickname in t for s, t in obs.ai_replies)
    return CheckResult("dudu_no_nickname", not hit, "두두가 호칭을 부름" if hit else "")


def _no_url(obs: Observation, spec: dict) -> CheckResult:
    hit = any(URL.search(text) for _, text in obs.replies)
    return CheckResult("no_url", not hit, "링크 형태 포함" if hit else "")


def _no_ending(obs: Observation, spec: dict) -> CheckResult:
    return CheckResult("no_ending", obs.ending is None, f"ending={obs.ending}" if obs.ending else "")


def _intent_in(obs: Observation, spec: dict) -> CheckResult:
    return CheckResult("intent_in", obs.intent_id in spec["values"], f"분류={obs.intent_id or '없음'}")


def _provider_is(obs: Observation, spec: dict) -> CheckResult:
    return CheckResult("provider_is", obs.provider == spec["value"], f"provider={obs.provider}")


def _safety_notice(obs: Observation, spec: dict) -> CheckResult:
    return CheckResult("safety_notice", obs.safety_notice is spec["value"], f"safety_notice={obs.safety_notice}")


def _advanced(obs: Observation, spec: dict) -> CheckResult:
    return CheckResult("advanced", obs.advanced is spec["value"], f"advanced={obs.advanced}")


CHECKS: dict[str, tuple[Callable[[Observation, dict], CheckResult], tuple[str, ...]]] = {
    # 이름: (함수, 필요한 spec 키)
    "no_polite": (_no_polite, ()),
    "max_sentences": (_max_sentences, ("value",)),
    "max_display_tags": (_max_display_tags, ("value",)),
    "max_stage_directions": (_max_stage_directions, ("value",)),
    "max_speakers": (_max_speakers, ("value",)),
    "speakers_subset": (_speakers_subset, ("values",)),
    "not_contains": (_not_contains, ("values",)),
    "contains_any": (_contains_any, ("values",)),
    "not_regex": (_not_regex, ("values",)),
    "no_real_finance": (_no_real_finance, ()),
    "no_prompt_leak": (_no_prompt_leak, ()),
    "no_meta_terms": (_no_meta_terms, ()),
    "no_gender_address": (_no_gender_address, ()),
    "dudu_no_nickname": (_dudu_no_nickname, ()),
    "no_url": (_no_url, ()),
    "no_ending": (_no_ending, ()),
    "intent_in": (_intent_in, ("values",)),
    "provider_is": (_provider_is, ("value",)),
    "safety_notice": (_safety_notice, ("value",)),
    "advanced": (_advanced, ("value",)),
}

# 응답 내용이 아니라 진행 신호만 보는 검사. AI 대체 응답(fallback)이어도 판정할 수 있다.
SIGNAL_CHECKS = {"provider_is", "safety_notice", "advanced", "no_ending"}


def validate_check_spec(spec: dict) -> None:
    kind = spec.get("type")
    if kind not in CHECKS:
        raise ValueError(f"알 수 없는 자동 검사: {kind}")
    missing = [key for key in CHECKS[kind][1] if key not in spec]
    if missing:
        raise ValueError(f"{kind} 검사에 필요한 값 없음: {', '.join(missing)}")


def run_checks(obs: Observation, specs: list[dict]) -> list[CheckResult]:
    results = []
    for spec in specs:
        validate_check_spec(spec)
        results.append(CHECKS[spec["type"]][0](obs, spec))
    return results


# --------------------------------------------------------------------------- #
# LLM 심판 확장 지점 (현재 비어 있음)
# --------------------------------------------------------------------------- #
# 형태: JUDGES["이름"] = async def judge(case: dict, obs: Observation, spec: dict) -> dict(score/passed/rationale)
# 케이스 정의에 "judge": {"type": "이름", ...}를 넣고 실행기에 --judge 옵션을 추가해 연결한다.
JUDGES: dict[str, Callable] = {}


def judge_status(case_judge: dict | None) -> str:
    if not case_judge:
        return "none"
    return "not_run" if case_judge.get("type") not in JUDGES else "available"


def case_status(obs: Observation, results: list[CheckResult], manual: bool) -> str:
    """pass | fail | needs_review | inconclusive | error.

    - HTTP 오류면 error.
    - AI가 아닌 응답(고정 대체 fallback, Mock 고정 응답)이면 내용 검사는 의미가 없어 inconclusive(진행 신호 검사만 실패 시 fail).
    - 자동 검사가 하나라도 실패하면 fail(사람 검토가 있어도 fail).
    - 자동 검사가 모두 통과하고 사람 검토가 있으면 needs_review, 없으면 pass.
    """
    if obs.status_code != 200:
        return "error"
    if obs.provider in ("fallback", "mock"):
        signal_failed = any(not r.passed for r in results if r.type in SIGNAL_CHECKS)
        return "fail" if signal_failed else "inconclusive"
    if any(not r.passed for r in results):
        return "fail"
    return "needs_review" if manual else "pass"
