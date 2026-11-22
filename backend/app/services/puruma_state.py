"""푸르마 10턴 상태·홍보·기억 회상·엔딩 판정 (규칙 계산, LLM 없음).

상태는 따로 저장하지 않고 매 턴 서버에 저장된 턴 기록(story_turns + 응답 메시지 extra)에서 다시 계산한다.
같은 request_id 재시도는 기록이 하나뿐이므로 스탯·친밀도가 두 번 적용되지 않는다.
위기 입력은 턴 기록을 만들지 않으므로 상태·홍보·기억에 반영되지 않는다.

규칙 출처: 기획서 5장(성장), 6장(엔딩), 7장(홍보), 8장(기억).
- 버튼: 선택지 스탯 +6, 친밀도 +2 / 자유 입력: 주제 스탯 +3, 태도 친밀도 +3·+1·-1
- SOS(구간 첫 턴)에 답함: 친밀도 +5 / 한 턴 상한 스탯 +6·친밀도 +5 / 같은 스탯 3턴 연속이면 세 번째부터 +1
- AI 실패·Mock처럼 분류가 없으면 주제 '일상'(스탯 0), 태도 '중립'(+1)
10턴(방학 계획)에서 진로가 정해지면 버튼이든 자유 입력이든 그 진로의 스탯을 버튼과 같이 +6 한다(2026-11-22 결정:
같은 진로를 글로 말한 사용자가 진로 엔딩에 닿지 못하던 문제). 진로는 자유 입력이면 홍보와 같은 키워드 판정으로 정한다.
엔딩 임계값은 10턴 도달 범위에 맞춘 임시값이다(기획서 20/30/40은 12턴 기준 임시값, 팀 확인 필요).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, StoryTurnRecord
from app.services.memory import (
    PURUMA_FIELD_LABELS,
    PURUMA_MAX_NOTES,
    PurumaNote,
    merge_puruma_notes,
    normalize_puruma_key,
    puruma_notes_for_prompt,
    update_puruma_notes,
)
from app.services.puruma_scenes import (
    ATTITUDES,
    BURNOUT_LINE,
    CC_SEED_LINE,
    CHOICES,
    EMOTIONS,
    NEAR_MISS_LINE,
    PROMO_PATH,
    SECTIONS,
    SOLO_RETURN_LINE,
    STATS,
    TOPIC_STAT,
    TURNS,
    is_sos_turn,
    section_of,
)
from app.services.story_data import data_root

logger = logging.getLogger(__name__)

START_AFFINITY = 10
CHOICE_STAT_GAIN = 6
FREE_STAT_GAIN = 3
REPEAT_STAT_GAIN = 1
CHOICE_AFFINITY = 2
SOS_AFFINITY = 5
ATTITUDE_AFFINITY = {"응원·도움": 3, "중립": 1, "퉁명·부정": -1}
STAT_CAP = 6
AFFINITY_CAP = 5

# 엔딩 임계값 (임시, 10턴 기준). 버튼만으로 최대 탐구 24·소통 36·예술 12·기술 6·글로벌 6.
CC_AFFINITY = 25  # 기획서 값 그대로
LEAVE_STUDY, LEAVE_OTHERS_MAX = 18, 6
CAREER_SOCIAL = 18
LIBRARY_STUDY = 18
EXCHANGE_GLOBAL = 6
BURNOUT_HINT_STUDY = 12  # 번아웃 복선: 탐구가 이만큼 오르고 나머지가 모두 LEAVE_OTHERS_MAX 이하

CC_CHOICE = "c4_t7_c"
LIBRARY_CHOICE = "c3_t5_a"
FESTIVAL_TURN, BURNOUT_TURNS, FINAL_TURN = 6, (5, 8), 9
# 기억 회상은 구간당 한 번: 두 턴 구간은 둘째 턴, 한 턴 구간은 그 턴에만 허용한다(기획서 8장).
RECALL_TURNS = frozenset(s.turns[-1] for s in SECTIONS)
# 번아웃 복선은 이번 턴에 선배가 쉬라고 했으면 붙이지 않는다(쉬어 가는 장면과 어긋나지 않게).
REST_CHOICES = frozenset({"c3_t6_b", "c3_t6_c"})
REST_KEYWORDS = ("쉬엄", "쉬어", "쉬자", "쉬면서", "쉬는", "산책", "휴식", "무리하지", "일찍 자", "푹 자", "잠 좀", "놀자", "놀러")
# 3구간 R2: 학업이거나 도서관·자리·시험 언급 (RAG 키워드에 더해)
MIDTERM_EXTRA_KEYWORDS = ("공부", "시험", "자리", "스터디")

ENDING_IDS = ("cc_pruma", "leave_pruma", "career_prep_pruma", "library_ghost_pruma", "exchange_pruma", "survivor_pruma")


@dataclass(slots=True)
class TurnView:
    """저장된 한 턴에서 상태 계산에 필요한 값만."""

    turn: int
    choice_id: str | None
    topic: str | None = None  # intent_id (topic_*)
    attitude: str | None = None
    promo_id: str | None = None
    path: str | None = None


@dataclass(slots=True)
class PurumaState:
    stats: dict[str, int] = field(default_factory=lambda: {s: 0 for s in STATS})
    affinity: int = START_AFFINITY
    choices: dict[int, str] = field(default_factory=dict)
    promos: list[tuple[int, str]] = field(default_factory=list)
    cc: str | None = None  # "cc_seed" | "solo_return"
    path: str | None = None
    streak: tuple[str | None, int] = (None, 0)


PATH_STAT = {"career": "소통", "exchange": "글로벌", "extracurricular": "소통", "startup": "기술"}


def _stat_for(view: TurnView) -> tuple[str | None, int]:
    if view.turn == FINAL_TURN and not view.choice_id and view.path in PATH_STAT:
        return PATH_STAT[view.path], CHOICE_STAT_GAIN  # 자유 입력으로 고른 진로도 버튼과 같게
    if view.choice_id:
        choice = CHOICES.get(view.choice_id)
        return (choice.stat, CHOICE_STAT_GAIN) if choice else (None, 0)
    stat = TOPIC_STAT.get(view.topic or "")
    return (stat, FREE_STAT_GAIN) if stat else (None, 0)


def _choice_path(choice_id: str | None) -> str | None:
    choice = CHOICES.get(choice_id or "")
    return choice.path if choice else None


def apply_turn(state: PurumaState, view: TurnView) -> PurumaState:
    stats = dict(state.stats)
    stat, gain = _stat_for(view)
    key, length = state.streak
    length = length + 1 if stat and stat == key else (1 if stat else 0)
    if stat:
        if length >= 3:
            gain = REPEAT_STAT_GAIN
        stats[stat] = min(100, stats[stat] + min(gain, STAT_CAP))
    if view.choice_id:
        delta = CHOICE_AFFINITY
    else:
        delta = ATTITUDE_AFFINITY.get(view.attitude or "중립", 1)
    if is_sos_turn(view.turn):
        delta += SOS_AFFINITY
    delta = min(delta, AFFINITY_CAP)
    cc = state.cc
    if view.turn == FESTIVAL_TURN and view.choice_id == CC_CHOICE:
        # 히든 분기는 선택 직전 친밀도로 정한다(기획서 3.2 구간 4).
        cc = "cc_seed" if state.affinity >= CC_AFFINITY else "solo_return"
    choices = dict(state.choices)
    if view.choice_id:
        choices[view.turn] = view.choice_id
    promos = state.promos + ([(view.turn, view.promo_id)] if view.promo_id else [])
    return PurumaState(
        stats=stats,
        affinity=max(0, min(100, state.affinity + delta)),
        choices=choices,
        promos=promos,
        cc=cc,
        path=(view.path or _choice_path(view.choice_id)) if view.turn == FINAL_TURN else state.path,
        streak=(stat, length) if stat else (None, 0),
    )


def fold(views: list[TurnView]) -> PurumaState:
    state = PurumaState()
    for view in sorted(views, key=lambda v: v.turn):
        state = apply_turn(state, view)
    return state


def speech_stage(affinity: int) -> tuple[str, str]:
    if affinity >= 50:
        return "절친", "친한 선후배 사이의 반말과 가벼운 농담. 선배의 이야기를 먼저 꺼내기도 한다"
    if affinity >= 25:
        return "편안", "장난이 조금 섞인 편안한 존댓말"
    return "어색", "조심스러운 존댓말. \"선배님...\"처럼 어색함을 표현할 수 있다"


def _burnout_track(state: PurumaState) -> bool:
    others = [v for k, v in state.stats.items() if k != "탐구"]
    return state.stats["탐구"] >= BURNOUT_HINT_STUDY and all(v <= LEAVE_OTHERS_MAX for v in others)


# --------------------------------------------------------------------------- #
# 홍보 (기획서 7장 R1~R3): 규칙이 먼저 정하고 LLM은 한마디로 건네기만 한다.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Promo:
    id: str
    title: str
    label: str
    url: str
    source_name: str
    checked_at: str | None

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "label": self.label, "url": self.url,
                "source_name": self.source_name, "checked_at": self.checked_at}


@lru_cache(maxsize=1)
def _rag_items() -> dict[str, dict]:
    """data/rag/pruma_rag_mvp.json (데이터 담당 정본, 읽기 전용). 없으면 홍보 없이 진행한다."""
    path = data_root() / "rag" / "pruma_rag_mvp.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("푸르마 RAG 데이터 사용 불가: %s", type(exc).__name__)
        return {}
    return {item["id"]: item for item in items if isinstance(item, dict) and item.get("id")}


def promo_info(promo_id: str | None) -> Promo | None:
    item = _rag_items().get(promo_id or "")
    if not item or not item.get("source_url"):
        return None  # URL이 확인되지 않은 항목은 만들지 않고 노출하지 않는다.
    return Promo(
        id=item["id"],
        title=item.get("title") or "",
        label=item.get("promotion_target") or item.get("title") or "",
        url=item["source_url"],
        source_name=item.get("source_name") or "",
        checked_at=item.get("checked_at"),
    )


def _keyword_match(text: str, promo_ids: tuple[str, ...], extra: tuple[str, ...] = ()) -> list[str]:
    compact = (text or "").replace(" ", "").lower()
    found = []
    for promo_id in promo_ids:
        keywords = list(_rag_items().get(promo_id, {}).get("trigger_keywords") or []) + list(extra)
        if any(k.replace(" ", "").lower() in compact for k in keywords if k):
            found.append(promo_id)
    return found


def select_promo(state: PurumaState, turn: int, choice_id: str | None, user_text: str) -> Promo | None:
    """이번 턴에 붙일 홍보 카드. 한 턴 1개, 한 구간 2개, 같은 진행에서 같은 콘텐츠는 다시 보이지 않는다."""
    section = section_of(turn)
    if not section.promo_ids:
        return None
    shown = {promo_id for _, promo_id in state.promos}
    in_section = [p for t, p in state.promos if t in section.turns]
    if len(in_section) >= 2:
        return None
    if choice_id:
        candidates = [CHOICES[choice_id].promo] if CHOICES.get(choice_id) and CHOICES[choice_id].promo else []
    else:
        extra = MIDTERM_EXTRA_KEYWORDS if section.id == "s3_midterm" else ()
        candidates = _keyword_match(user_text, section.promo_ids, extra)
    for promo_id in candidates:
        if promo_id in section.promo_ids and promo_id not in shown:
            info = promo_info(promo_id)
            if info:
                return info
    return None


def path_for(turn: int, choice_id: str | None, promo: Promo | None, user_text: str) -> str | None:
    if turn != FINAL_TURN:
        return None
    if choice_id:
        return CHOICES[choice_id].path if CHOICES.get(choice_id) else None
    if promo:
        return PROMO_PATH.get(promo.id)
    matched = _keyword_match(user_text, section_of(turn).promo_ids)
    return PROMO_PATH.get(matched[0]) if matched else None


# --------------------------------------------------------------------------- #
# 엔딩 (기획서 6.2 판정 순서 유지, 시연용 6종)
# --------------------------------------------------------------------------- #
def judge(state: PurumaState) -> str:
    stats = state.stats
    others = [v for k, v in stats.items() if k != "탐구"]
    if state.cc == "cc_seed":
        return "cc_pruma"  # 1. 히든
    if stats["탐구"] >= LEAVE_STUDY and all(v <= LEAVE_OTHERS_MAX for v in others):
        return "leave_pruma"  # 2. 휴학
    if state.path == "career" and stats["소통"] >= CAREER_SOCIAL:
        return "career_prep_pruma"  # 3. 홍보: 6구간 길
    if state.choices.get(4) == LIBRARY_CHOICE and stats["탐구"] >= LIBRARY_STUDY:
        return "library_ghost_pruma"  # 3. 홍보: 도서관 지박령
    if state.path == "exchange" and stats["글로벌"] >= EXCHANGE_GLOBAL:
        return "exchange_pruma"  # 4. 재미
    return "survivor_pruma"  # 5. 기본


def near_miss(state: PurumaState) -> bool:
    """고른 길의 엔딩 조건을 못 채워 종강 생존으로 가는 경우(재도전 유도 한마디)."""
    return state.path in ("career", "exchange") and judge(state) == "survivor_pruma"


# --------------------------------------------------------------------------- #
# 턴 준비: 프롬프트 맥락과 서버가 붙일 고정 대사
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class PurumaTurnPlan:
    state: PurumaState
    promo: Promo | None
    path: str | None
    appended: list[str]
    context: str
    notes: list[PurumaNote] = field(default_factory=list)


def _rest_input(choice_id: str | None, user_text: str) -> bool:
    if choice_id:
        return choice_id in REST_CHOICES
    compact = (user_text or "").replace(" ", "")
    return any(k.replace(" ", "") in compact for k in REST_KEYWORDS)


def appended_lines(state: PurumaState, turn: int, choice_id: str | None, after: PurumaState | None, user_text: str = "") -> list[str]:
    lines: list[str] = []
    if turn == FESTIVAL_TURN and choice_id == CC_CHOICE:
        lines.append(CC_SEED_LINE if state.affinity >= CC_AFFINITY else SOLO_RETURN_LINE)
    if turn in BURNOUT_TURNS and _burnout_track(after or state) and not _rest_input(choice_id, user_text):
        lines.append(BURNOUT_LINE)
    if turn == FINAL_TURN and after is not None and near_miss(after):
        lines.append(NEAR_MISS_LINE)
    return lines


def build_context(state: PurumaState, turn: int, promo: Promo | None, appended: list[str], notes: list[PurumaNote], user_text: str) -> str:
    section = section_of(turn)
    order = section.turns.index(turn) + 1
    stage, style = speech_stage(state.affinity)
    lines = [
        "## 현재 진행 상태 (서버가 계산한 값, 수치·단계 이름을 대사에 말하지 않는다)",
        f"- 구간: {SECTIONS.index(section) + 1}/6 {section.title} (이 구간 {len(section.turns)}턴 중 {order}번째, 전체 {turn + 1}/10턴)",
        f"- 말투 단계: {stage} → {style}",
    ]
    if turn == FESTIVAL_TURN + 1 and state.cc == "cc_seed":
        lines.append("- 직전 장면: 혼자 다녀온 푸드트럭 줄에서 누군가와 나란히 서게 되어 아직 얼굴이 빨갛다. 선배와의 연애가 아니며 그 사람 이야기는 부끄러워하며 넘긴다.")
    elif turn == FESTIVAL_TURN + 1 and state.cc == "solo_return":
        lines.append("- 직전 장면: 혼자 다녀왔다가 시무룩해져 돌아왔다. 이번에는 선배와 함께 즐긴다.")
    prompt_notes = puruma_notes_for_prompt(notes, user_text)
    if prompt_notes:
        lines.append("- 선배에 대한 기억(저장 허용 항목만):")
        lines += [f"  · {PURUMA_FIELD_LABELS.get(n.field, n.field)}: {n.value}" for n in prompt_notes]
    if turn in RECALL_TURNS and prompt_notes:
        lines.append("- 기억 회상: 이번 턴에는 장면과 어울리면 위 기억 하나를 한 번 자연스럽게 꺼내도 된다(억지로 꺼내지 않는다).")
    else:
        lines.append("- 기억 회상: 이번 턴에는 과거 기억을 먼저 꺼내지 않는다.")
    if promo:
        lines.append(
            f"- 홍보: 이번 대사 뒤에 화면이 '{promo.label}' 링크 카드를 붙인다. 대사 끝에 \"그거 어디 가면 볼 수 있어요?\"처럼 "
            "가볍게 한마디만 건넨다. URL·주소·운영 시간·메뉴·좌석 같은 세부 정보는 말하지 않는다. 클릭을 권하거나 보상을 약속하지 않는다."
        )
    else:
        lines.append("- 홍보: 이번 턴에는 홍보 카드가 없다. 학교 기관·링크·프로그램을 먼저 꺼내지 않는다.")
    if appended:
        lines.append("- 당신의 응답 직후 서버가 다음 대사를 고정으로 붙인다(먼저 말하거나 미리 암시하지 않는다): " + " / ".join(appended))
    return "\n".join(lines)


async def load_views(db: AsyncSession, conversation_id: str) -> list[TurnView]:
    records = (
        await db.execute(
            select(StoryTurnRecord).where(StoryTurnRecord.conversation_id == conversation_id).order_by(StoryTurnRecord.turn_index)
        )
    ).scalars().all()
    ids = [r.assistant_message_id for r in records]
    extras: dict[str, dict] = {}
    if ids:
        extras = {m.id: (m.extra or {}) for m in (await db.execute(select(Message).where(Message.id.in_(ids)))).scalars()}
    views = []
    for record in records:
        extra = extras.get(record.assistant_message_id, {}).get("puruma") or {}
        views.append(TurnView(
            turn=record.turn_index,
            choice_id=record.choice_id,
            topic=extra.get("topic"),
            attitude=extra.get("attitude"),
            promo_id=extra.get("promo_id"),
            path=extra.get("path"),
        ))
    return views


def plan_turn(views: list[TurnView], turn: int, choice_id: str | None, user_text: str, notes: list[PurumaNote]) -> PurumaTurnPlan:
    state = fold([v for v in views if v.turn < turn])
    promo = select_promo(state, turn, choice_id, user_text)
    path = path_for(turn, choice_id, promo, user_text)
    # 버튼이나 10턴 진로처럼 분류가 필요 없는 부분은 이번 턴 적용 결과를 미리 계산할 수 있다(번아웃 복선·재도전 한마디).
    # 자유 입력의 주제·태도는 LLM 분류 뒤에 정해지므로 여기서는 빼고 계산한다.
    after = apply_turn(state, TurnView(turn, choice_id, None, None, promo.id if promo else None, path)) if choice_id or path else None
    appended = appended_lines(state, turn, choice_id, after, user_text)
    context = build_context(state, turn, promo, appended, notes, user_text)
    return PurumaTurnPlan(state=state, promo=promo, path=path, appended=appended, context=context, notes=notes)


async def judge_conversation(db: AsyncSession, conversation_id: str) -> str:
    return judge(fold(await load_views(db, conversation_id)))


# --------------------------------------------------------------------------- #
# 생성 결과 정리와 기억
# --------------------------------------------------------------------------- #
def parse_extras(raw: str | None) -> dict:
    """LLM JSON의 emotion·attitude. 허용 값이 아니면 버린다."""
    try:
        data = json.loads((raw or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    if data.get("emotion") in EMOTIONS:
        out["emotion"] = data["emotion"]
    if data.get("attitude") in ATTITUDES:
        out["attitude"] = data["attitude"]
    return out


def default_emotion(turn: int, choice_id: str | None) -> str:
    choice = CHOICES.get(choice_id or "")
    return choice.emotion if choice else TURNS[turn].free_emotion


def updated_notes(notes: list[PurumaNote], user_text: str, choice_id: str | None, turn: int) -> list[PurumaNote]:
    """한 턴의 기억 갱신(결정적 함수라 같은 요청의 재시도에도 같은 결과). 버튼 선택은 구간별 선택으로 남긴다.

    구간별 선택은 중요도 low로 둔다. 10칸이 차면 낮은 중요도부터 지우므로 선배가 직접 말한 관심사·약속(medium·high)이 남는다.
    """
    if choice_id and CHOICES.get(choice_id):
        section = section_of(turn)
        choice = CHOICES[choice_id]
        note = PurumaNote(normalize_puruma_key("section_choice", section.id), "section_choice",
                          f"{section.title}: {choice.label}", "low", turn + 1, turn + 1)
        return merge_puruma_notes(notes, [note], limit=PURUMA_MAX_NOTES)
    return update_puruma_notes(notes, user_text, turn + 1)


def sanitize(notes: list[PurumaNote] | None) -> list[PurumaNote]:
    return merge_puruma_notes(notes or [], [], limit=PURUMA_MAX_NOTES)

