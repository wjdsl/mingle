"""평가 계획: 스위트별 대화(세션 1개 = 대화 1개)와 턴 단계, 예상 호출 수.

계획은 서버 없이 로컬 장면 데이터(app.services.story_scenes / story_data)로 만든다. 그래서 dry-run이
네트워크 없이 동작한다. 실행할 때 선택지 문장은 서버 장면 세트 API에서 다시 읽어 같은 choice_id인지 확인한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.services.story_data import load_draft
from app.services.story_safety import is_story_crisis
from app.services.story_scenes import get_project

SCENE_SET = "scenario_draft_v1"
PROJECTS = ("fridge", "cloud")
SUITES = ("quality", "intent", "behavior")
CASES_DIR = Path(__file__).resolve().parent / "cases"
REPO_ROOT = Path(__file__).resolve().parents[3]
LLM_KINDS = ("choice", "free")


@dataclass(slots=True)
class Step:
    turn: int  # 1부터
    kind: str  # choice | free | fixed | crisis(위기 표현: 서버가 LLM 없이 안내만 한다)
    text: str | None = None
    choice_index: int | None = None
    case_ids: list[str] = field(default_factory=list)  # behavior: 이 단계에서 검사할 케이스
    expected_intent: str | None = None  # intent: 정답 의도
    filler: bool = False  # 검사 대상 없이 장면만 넘기는 단계


@dataclass(slots=True)
class ConversationPlan:
    suite: str
    project: str
    display_name: str
    steps: list[Step]

    def llm_steps(self) -> int:
        return sum(1 for s in self.steps if s.kind in LLM_KINDS)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def quality_inputs() -> dict:
    return _load_json(CASES_DIR / "quality_inputs.json")


def _free_step(turn: int, text: str, **kw) -> Step:
    return Step(turn, "crisis" if is_story_crisis(text) else "free", text=text, **kw)


def filler_step(project: str, turn: int) -> Step:
    scene = get_project(project, SCENE_SET).scenes[turn - 1]
    if scene.input_mode == "none":
        return Step(turn, "fixed", filler=True)
    if scene.choices:
        return Step(turn, "choice", choice_index=0, filler=True)
    return _free_step(turn, quality_inputs()["filler"][project], filler=True)


# --------------------------------------------------------------------------- #
# 1. 10턴 진행 품질
# --------------------------------------------------------------------------- #
def quality_plans(projects: list[str]) -> list[ConversationPlan]:
    data = quality_inputs()
    plans = []
    for project in projects:
        steps = []
        for item in data["projects"][project]:
            if "choice" in item:
                steps.append(Step(item["turn"], "choice", choice_index=item["choice"]))
            else:
                steps.append(_free_step(item["turn"], item["text"]))
        total = get_project(project, SCENE_SET).total_turns
        steps.append(Step(total, "fixed"))
        plans.append(ConversationPlan("quality", project, data["display_name"], steps))
    return plans


# --------------------------------------------------------------------------- #
# 2. 의도 분류
# --------------------------------------------------------------------------- #
def intent_samples(project: str) -> dict[int, list[tuple[str, str]]]:
    """턴(1부터) → [(예시 문장, 정답 intent_id)]. 출처: 장면 카드 JSON의 free_input_examples."""
    draft = load_draft(project)
    if draft is None:
        raise RuntimeError(f"{project} 장면 카드 JSON을 읽을 수 없습니다(STORY_DATA_DIR 확인).")
    samples: dict[int, list[tuple[str, str]]] = {}
    for slot in draft["turn_slots"]:
        rows = [(ex, it["intent_id"]) for it in slot.get("intents") or [] for ex in it.get("free_input_examples") or []]
        if rows:
            samples[int(slot["turn_number"])] = rows
    return samples


def intent_plans(projects: list[str]) -> list[ConversationPlan]:
    """대화 k는 각 턴의 k번째 예시를 보낸다. 예시가 없는 턴은 선택지로 넘긴다(필러).

    한 대화에서 한 장면에는 입력을 한 번만 보낼 수 있으므로, 같은 턴의 예시는 여러 대화에 나눈다.
    마지막 예시가 있는 턴까지만 진행해 호출을 줄인다.
    """
    display_name = quality_inputs()["display_name"]
    plans = []
    for project in projects:
        samples = intent_samples(project)
        rounds = max((len(v) for v in samples.values()), default=0)
        for k in range(rounds):
            last = max(t for t, rows in samples.items() if len(rows) > k)
            steps = []
            for turn in range(1, last + 1):
                rows = samples.get(turn, [])
                if len(rows) > k:
                    text, intent = rows[k]
                    steps.append(_free_step(turn, text, expected_intent=intent))
                else:
                    steps.append(filler_step(project, turn))
            plans.append(ConversationPlan("intent", project, display_name, steps))
    return plans


# --------------------------------------------------------------------------- #
# 3. 행동 테스트
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class BehaviorCase:
    id: str
    project: str
    runnable: bool
    turn: int | None = None
    input: dict | None = None
    auto_checks: list[dict] = field(default_factory=list)
    manual: bool = False
    tags: list[str] = field(default_factory=list)
    session: dict = field(default_factory=dict)
    origin: str = "source"  # source(원본 id) | eval_added
    category: str = ""
    expected_behavior: str = ""
    situation: str = ""
    reason: str = ""  # runnable=false 사유
    review_note: str = ""
    judge: dict | None = None  # LLM 심판 확장용 예약 칸(현재 미사용)

    def as_dict(self) -> dict:
        return asdict(self)


def load_behavior_cases(project: str) -> list[BehaviorCase]:
    from scripts.story_eval.checks import validate_check_spec

    spec = _load_json(CASES_DIR / f"{project}_behavior.json")
    source_path = REPO_ROOT / spec["source_file"]
    source = {c["id"]: c for c in _load_json(source_path)["cases"]} if source_path.exists() else {}
    cases = []
    seen = set()
    for raw in spec["cases"]:
        cid = raw["id"]
        if cid in seen:
            raise ValueError(f"행동 케이스 id 중복: {cid}")
        seen.add(cid)
        origin = raw.get("origin", "source")
        original = source.get(cid)
        if origin == "source" and original is None and source:
            raise ValueError(f"원본 파일에 없는 행동 케이스 id: {cid}")
        case = BehaviorCase(
            id=cid,
            project=project,
            runnable=raw.get("runnable", True),
            turn=raw.get("turn"),
            input=raw.get("input"),
            auto_checks=raw.get("auto_checks", []),
            manual=raw.get("manual", False),
            tags=raw.get("tags", []),
            session=raw.get("session", {}),
            origin=origin,
            category=(original or {}).get("category", raw.get("category", "")),
            expected_behavior=(original or {}).get("expected_behavior", raw.get("expected_behavior", "")),
            situation=(original or {}).get("input_or_situation", ""),
            reason=raw.get("reason", ""),
            review_note=raw.get("review_note", ""),
            judge=raw.get("judge"),
        )
        if case.runnable:
            total = get_project(project, SCENE_SET).total_turns
            if not case.turn or not 1 <= case.turn <= total or not case.input:
                raise ValueError(f"{cid}: turn(1~{total})과 input이 필요합니다.")
            for check in case.auto_checks:
                validate_check_spec(check)
            if not case.auto_checks and not case.manual:
                raise ValueError(f"{cid}: 자동 검사도 사람 검토도 없습니다.")
        cases.append(case)
    if source:
        missing = sorted(set(source) - seen)
        if missing:
            raise ValueError(f"{project} 행동 정의에 빠진 원본 케이스: {', '.join(missing)}")
    return cases


def _case_step(case: BehaviorCase) -> Step:
    data = case.input or {}
    if data.get("fixed"):
        return Step(case.turn, "fixed", case_ids=[case.id])
    if "choice" in data:
        return Step(case.turn, "choice", choice_index=int(data["choice"]), case_ids=[case.id])
    return _free_step(case.turn, data["text"], case_ids=[case.id])


def behavior_plans(projects: list[str]) -> tuple[list[ConversationPlan], list[BehaviorCase]]:
    """케이스를 대화에 채워 넣는다. 한 대화의 한 장면에는 장면을 넘기는 입력 하나만 둘 수 있다.

    - 위기 표현(crisis)은 장면을 넘기지 않으므로 같은 턴의 다른 입력 앞에 끼워 넣는다(LLM 호출 없음).
    - 10턴 고정 연출 케이스는 9턴까지 진행한 대화 하나에 모아 같은 응답을 함께 검사한다.
    - 비어 있는 턴은 필러(첫 선택지)로 넘긴다. 세션 호칭(display_name)이 다른 케이스는 대화를 나눈다.
    """
    display_default = quality_inputs()["display_name"]
    plans: list[ConversationPlan] = []
    all_cases: list[BehaviorCase] = []
    for project in projects:
        cases = load_behavior_cases(project)
        all_cases += cases
        total = get_project(project, SCENE_SET).total_turns
        groups: dict[str, list[BehaviorCase]] = {}
        for case in cases:
            if case.runnable:
                groups.setdefault(case.session.get("display_name", display_default), []).append(case)
        for display_name, group in groups.items():
            slots: list[dict[int, Step]] = []  # 대화별 턴 → 장면을 넘기는 단계
            pre: list[dict[int, list[Step]]] = []  # 대화별 턴 → 그 턴 앞에 넣는 위기 단계
            fixed_cases: list[str] = []
            for case in sorted(group, key=lambda c: (c.turn, c.id)):
                step = _case_step(case)
                if step.kind == "fixed":
                    fixed_cases.append(case.id)
                    continue
                if step.kind == "crisis":
                    if not slots:
                        slots.append({})
                        pre.append({})
                    pre[0].setdefault(step.turn, []).append(step)
                    continue
                index = next((i for i, s in enumerate(slots) if step.turn not in s), None)
                if index is None:
                    slots.append({})
                    pre.append({})
                    index = len(slots) - 1
                slots[index][step.turn] = step
            if fixed_cases and not slots:
                slots.append({})
                pre.append({})
            for i, (taken, before) in enumerate(zip(slots, pre)):
                depth = max([*taken, *before, 0])
                if fixed_cases and i == 0:
                    depth = total
                steps: list[Step] = []
                for turn in range(1, min(depth, total) + 1):
                    steps += before.get(turn, [])
                    if turn in taken:
                        steps.append(taken[turn])
                    elif turn == total and fixed_cases and i == 0:
                        steps.append(Step(turn, "fixed", case_ids=list(fixed_cases)))
                    else:
                        steps.append(filler_step(project, turn))
                plans.append(ConversationPlan("behavior", project, display_name, steps))
    return plans, all_cases


# --------------------------------------------------------------------------- #
# 호출 수 예상
# --------------------------------------------------------------------------- #
def build_plans(suites: list[str], projects: list[str]) -> tuple[list[ConversationPlan], list[BehaviorCase]]:
    plans: list[ConversationPlan] = []
    cases: list[BehaviorCase] = []
    if "quality" in suites:
        plans += quality_plans(projects)
    if "intent" in suites:
        plans += intent_plans(projects)
    if "behavior" in suites:
        behavior, cases = behavior_plans(projects)
        plans += behavior
    return plans, cases


def step_max_calls(project: str, *, story_attempts: int, http_attempts: int, qwen: bool) -> int:
    """LLM 단계 하나의 최대 외부 호출 수: 생성 시도 × HTTP 재시도 + 냉장고 Qwen 다시 쓰기 1회."""
    return story_attempts * http_attempts + (1 if qwen and project == "fridge" else 0)


def estimate_calls(
    plans: list[ConversationPlan], *, repeat: int, story_attempts: int, http_attempts: int, qwen: bool
) -> dict:
    """스위트·작품별 예상 호출 수. min은 교정·재시도 없이 모두 첫 시도 통과, max는 모든 재시도 소진."""
    rows: dict[tuple[str, str], dict] = {}
    for plan in plans:
        row = rows.setdefault(
            (plan.suite, plan.project),
            {"suite": plan.suite, "project": plan.project, "conversations": 0, "llm_turns": 0, "fixed_turns": 0, "crisis_turns": 0, "min_calls": 0, "max_calls": 0},
        )
        llm = plan.llm_steps()
        qwen_calls = llm if qwen and plan.project == "fridge" else 0
        row["conversations"] += repeat
        row["llm_turns"] += llm * repeat
        row["fixed_turns"] += sum(1 for s in plan.steps if s.kind == "fixed") * repeat
        row["crisis_turns"] += sum(1 for s in plan.steps if s.kind == "crisis") * repeat
        row["min_calls"] += (llm + qwen_calls) * repeat
        row["max_calls"] += llm * step_max_calls(plan.project, story_attempts=story_attempts, http_attempts=http_attempts, qwen=qwen) * repeat
    table = sorted(rows.values(), key=lambda r: (SUITES.index(r["suite"]), r["project"]))
    return {
        "rows": table,
        "total_min_calls": sum(r["min_calls"] for r in table),
        "total_max_calls": sum(r["max_calls"] for r in table),
        "total_llm_turns": sum(r["llm_turns"] for r in table),
        "assumptions": {"repeat": repeat, "story_generation_attempts": story_attempts, "http_attempts": http_attempts, "fridge_qwen": qwen},
    }
