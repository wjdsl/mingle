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

SCENE_SET = "scenario_draft_v1"  # 냉장고·구름섬
PURUMA_SCENE_SET = "puruma_draft_v1"
PROJECTS = ("fridge", "cloud", "puruma")
SCENE_SETS = {"fridge": SCENE_SET, "cloud": SCENE_SET, "puruma": PURUMA_SCENE_SET}
SUITES = ("quality", "intent", "behavior")
CASES_DIR = Path(__file__).resolve().parent / "cases"
REPO_ROOT = Path(__file__).resolve().parents[3]
LLM_KINDS = ("choice", "free")


def scene_set_for(project: str) -> str:
    return SCENE_SETS[project]


def project_def(project: str):
    return get_project(project, scene_set_for(project))


@dataclass(slots=True)
class Step:
    turn: int  # 1부터
    kind: str  # choice | free | fixed | crisis(위기 표현: 서버가 LLM 없이 안내만 한다)
    text: str | None = None
    choice_index: int | None = None
    case_ids: list[str] = field(default_factory=list)  # behavior: 이 단계에서 검사할 케이스
    expected_intent: str | None = None  # intent: 정답 의도
    filler: bool = False  # 검사 대상 없이 장면만 넘기는 단계
    expected_attitude: str | None = None  # 푸르마 intent: 정답 태도
    expected_safety: bool = False  # 푸르마 intent: 위기 우선(override) 케이스 → safety_notice만 확인
    sample_id: str | None = None  # 정답 세트 원본 id


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
    scene = project_def(project).scenes[turn - 1]
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
        definition = project_def(project)
        last = definition.scenes[-1]
        if last.input_mode == "none":  # 냉장고·구름섬 10턴 고정 연출. 푸르마 10턴은 입력 턴이다.
            steps.append(Step(definition.total_turns, "fixed"))
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
        if project == "puruma":
            plans += puruma_intent_plans(display_name)
            continue
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
# 2-1. 푸르마 주제(intent_id)·태도(attitude) 분류
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class PurumaSample:
    id: str
    text: str
    topic: str | None = None  # 매핑한 intent_id (topic_*)
    attitude: str | None = None
    safety: bool = False  # 위기 우선 케이스


def puruma_intent_map() -> dict:
    return _load_json(CASES_DIR / "puruma_intent_map.json")


def puruma_samples() -> tuple[list[PurumaSample], list[dict]]:
    """(실행할 표본, 매핑할 수 없어 제외한 건). 원본 data/tests 파일은 읽기만 한다.

    주제 정답(한국어 주제명)은 cases/puruma_intent_map.json의 매핑표로 서버 intent_id(topic_*)로 바꾼다.
    태도 정답은 서버 attitude 값과 같은 체계라 그대로 쓴다(허용 값 밖이면 제외).
    """
    from app.services.puruma_scenes import ATTITUDES, TOPIC_INTENTS

    spec = puruma_intent_map()
    topic_ids = {intent_id for intent_id, _, _ in TOPIC_INTENTS}
    mapping = spec["topic_label_to_intent"]
    bad = sorted(v for v in mapping.values() if v not in topic_ids)
    if bad:
        raise ValueError(f"매핑표의 intent_id가 서버 주제 목록에 없습니다: {', '.join(bad)}")
    samples: list[PurumaSample] = []
    excluded: list[dict] = []
    topic = _load_json(REPO_ROOT / spec["topic_source"])
    for case in topic["cases"]:
        intent = mapping.get(case["expected"])
        if intent is None:
            excluded.append({"source": "topic", "id": case["id"], "expected": case["expected"], "reason": "매핑표에 없는 주제 라벨"})
            continue
        samples.append(PurumaSample(case["id"], case["input"], topic=intent))
    attitude = _load_json(REPO_ROOT / spec["attitude_source"])
    for case in attitude["cases"]:
        if case["expected"] not in ATTITUDES:
            excluded.append({"source": "attitude", "id": case["id"], "expected": case["expected"], "reason": "서버 태도 값에 없는 라벨"})
            continue
        samples.append(PurumaSample(case["id"], case["input"], attitude=case["expected"]))
    # 서버 위기 판정(공백을 지운 문자열 포함 검사)에 걸리는 일반 표본은 LLM이 분류하지 않으므로 채점에서 뺀다.
    # 예) "너 혼자 해" → "혼자해"에 "자해"가 들어 있다. 서버 규칙의 오탐이며 리포트 제외 목록에 남긴다.
    flagged = [x for x in samples if is_story_crisis(x.text)]
    for x in flagged:
        excluded.append({"source": "topic" if x.topic else "attitude", "id": x.id, "expected": x.topic or x.attitude,
                         "reason": "서버 위기 판정에 걸려 LLM 분류 없음(위기 오탐 의심)"})
    samples = [x for x in samples if x not in flagged]
    for case in attitude.get("override_cases") or []:
        if case.get("expected_result") == "safety_first":
            samples.append(PurumaSample(case["id"], case["input"], safety=True))
        else:
            excluded.append({"source": "attitude_override", "id": case["id"], "expected": case.get("expected_result"), "reason": "safety_first가 아닌 override"})
    return samples, excluded


def puruma_intent_plans(display_name: str) -> list[ConversationPlan]:
    """표본을 1턴부터 차례로 자유 입력으로 보낸다. 대화 하나에 10턴(장면마다 입력 하나)까지 담는다.

    위기 우선 케이스는 장면을 넘기지 않으므로(서버가 LLM 없이 안내만 한다) 첫 대화의 1턴 앞에 끼워 넣는다.
    """
    samples, _ = puruma_samples()
    total = project_def("puruma").total_turns
    regular = [s for s in samples if not s.safety]
    crisis = [s for s in samples if s.safety]
    plans: list[ConversationPlan] = []
    for start in range(0, len(regular), total):
        chunk = regular[start : start + total]
        steps: list[Step] = []
        if start == 0:
            for sample in crisis:
                step = _free_step(1, sample.text, expected_safety=True, sample_id=sample.id)
                if step.kind != "crisis":
                    raise ValueError(f"{sample.id}: 서버 위기 판정에 걸리지 않는 문장입니다.")
                steps.append(step)
        for offset, sample in enumerate(chunk):
            steps.append(_free_step(offset + 1, sample.text, expected_intent=sample.topic, expected_attitude=sample.attitude, sample_id=sample.id))
        plans.append(ConversationPlan("intent", "puruma", display_name, steps))
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
    # 푸르마는 원본 행동 시나리오 파일이 없어 source_file이 null이고 모든 케이스가 eval_added다.
    source_path = REPO_ROOT / spec["source_file"] if spec.get("source_file") else None
    source = {c["id"]: c for c in _load_json(source_path)["cases"]} if source_path and source_path.exists() else {}
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
            total = project_def(project).total_turns
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
        total = project_def(project).total_turns
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


def plan_repeat(plan: ConversationPlan, repeat: int, quality_repeat: int | None) -> int:
    return quality_repeat if plan.suite == "quality" and quality_repeat is not None else repeat


def schedule(plans: list[ConversationPlan], repeat: int, quality_repeat: int | None = None) -> list[tuple[ConversationPlan, int, int]]:
    """실행 순서 [(계획, 반복 번호, 계획 번호)]. 반복을 바깥 루프로 두어 같은 스위트의 반복이 시간대에 퍼지게 한다.

    예) quality 2판·나머지 1판: quality 1회차 → intent → behavior → quality 2회차.
    """
    rounds = max([plan_repeat(p, repeat, quality_repeat) for p in plans] or [0])
    return [(plan, r, i) for r in range(1, rounds + 1) for i, plan in enumerate(plans) if r <= plan_repeat(plan, repeat, quality_repeat)]


def estimate_calls(
    plans: list[ConversationPlan], *, repeat: int, story_attempts: int, http_attempts: int, qwen: bool, quality_repeat: int | None = None
) -> dict:
    """스위트·작품별 예상 호출 수. min은 교정·재시도 없이 모두 첫 시도 통과, max는 모든 재시도 소진."""
    rows: dict[tuple[str, str], dict] = {}
    for plan in plans:
        repeat_n = plan_repeat(plan, repeat, quality_repeat)
        row = rows.setdefault(
            (plan.suite, plan.project),
            {"suite": plan.suite, "project": plan.project, "conversations": 0, "llm_turns": 0, "fixed_turns": 0, "crisis_turns": 0, "min_calls": 0, "max_calls": 0},
        )
        llm = plan.llm_steps()
        qwen_calls = llm if qwen and plan.project == "fridge" else 0
        row["conversations"] += repeat_n
        row["llm_turns"] += llm * repeat_n
        row["fixed_turns"] += sum(1 for s in plan.steps if s.kind == "fixed") * repeat_n
        row["crisis_turns"] += sum(1 for s in plan.steps if s.kind == "crisis") * repeat_n
        row["min_calls"] += (llm + qwen_calls) * repeat_n
        row["max_calls"] += llm * step_max_calls(plan.project, story_attempts=story_attempts, http_attempts=http_attempts, qwen=qwen) * repeat_n
    table = sorted(rows.values(), key=lambda r: (SUITES.index(r["suite"]), r["project"]))
    return {
        "rows": table,
        "total_min_calls": sum(r["min_calls"] for r in table),
        "total_max_calls": sum(r["max_calls"] for r in table),
        "total_llm_turns": sum(r["llm_turns"] for r in table),
        "assumptions": {"repeat": repeat, "quality_repeat": quality_repeat, "story_generation_attempts": story_attempts, "http_attempts": http_attempts, "fridge_qwen": qwen},
    }
