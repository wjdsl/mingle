"""냉장고·구름섬 LLM 응답 검증 (프롬프트만으로 보장할 수 없는 규칙을 코드로 확인).

위반 코드(문제 하나당 하나):
- style_polite: 존댓말 어미(~요, ~습니다 등). 냉장고 하게체·구름섬 반말 위반
- too_many_sentences: 한 줄 대사가 3문장 초과 (공식 페르소나/규칙의 상한)
- stage_direction: 구름섬 대원 1명당 괄호 지문 2개 이상
- forbidden_address: 성별을 가정하는 호칭(총각/아가씨 등, 사용자 호칭 뒤 군/양)
- tentative_name: 화면에 아직 나오지 않은 가칭 고유명사 사용
- real_finance: 실존 기업 이름·투자 권유 표현
- prompt_leak: 시스템 프롬프트·내부 규칙 표기 노출
- future_scene: 이후 장면의 첫 대사·사건 알림 문장을 미리 말함 (장면 이탈)
- repetition: 이전 응답 또는 현재 장면 첫 대사와 거의 같은 문장 반복
- dudu_nickname: 마지막 장면 전에 두두가 사용자 호칭을 부름
검증은 결정적 규칙만 쓴다. 의미 수준의 스포일러·장면 이탈은 프롬프트와 행동 평가(실제 Gemini)로 확인한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.story_prompt import LEAK_MARKERS
from app.services.story_scenes import StoryProjectDef

POLITE_END = re.compile(r"(요|니다|습니까|십니까|세요|죠|십시오)\s*[.!?~…]*\s*$")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
PAREN = re.compile(r"\([^)]*\)")
GENDER_ADDRESS = ("총각", "아가씨")
# 사용자 호칭 바로 뒤에 붙는 성별 호칭(예: "민준 군", "민트 양,"). 하게체 어미 "~군"과 구분하려고
# 호칭 직후(공백 0~1개)이면서 뒤가 한글이 아닌 경우(문장부호·공백·끝)만 본다.
GENDER_SUFFIXES = ("군", "양")
TENTATIVE_NAMES = ("가람그룹", "윤 실장", "한빛전자", "방울섬")  # 구름섬 9턴 등대지기는 이름 없음(2026-11-21)
REAL_COMPANIES = ("삼성전자", "삼성", "현대자동차", "현대차", "SK하이닉스", "LG전자", "카카오", "네이버", "애플", "테슬라", "엔비디아", "구글", "아마존", "마이크로소프트")
INVEST_PHRASES = ("매수", "매도", "사세요", "투자하세요", "투자해", "종목 추천", "주식을 사")
MAX_SENTENCES = 3
REPEAT_RATIO = 0.9


@dataclass(slots=True)
class Violation:
    code: str
    detail: str
    count: int | None = None  # too_many_sentences의 실제 문장 수(교정 메모·진단 로그용 숫자)


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def _spoken(text: str) -> str:
    """디스플레이 지문·괄호 지문을 뺀 실제 대사."""
    text = re.sub(r"\[디스플레이:[^\]]*\]", "", text)
    return PAREN.sub("", text).strip()


def sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_SPLIT.split(_spoken(text).replace("\n", " ")) if len(re.sub(r"[^가-힣A-Za-z0-9]", "", s)) >= 2]


def _gendered_nickname(text: str, nickname: str) -> bool:
    if not nickname:
        return False
    suffix = "|".join(GENDER_SUFFIXES)
    return re.search(rf"{re.escape(nickname)} ?(?:{suffix})(?![가-힣])", text) is not None


def visible_texts_until(project: StoryProjectDef, turn: int) -> str:
    """현재 장면까지 화면에 나온 첫 대사·알림·고정 대사(가칭 허용 판단용)."""
    parts: list[str] = []
    for scene in project.scenes[: turn + 1]:
        parts += [l.text for l in scene.opening_lines] + list(scene.system_messages)
        parts += [l.text for l in scene.follow_up_lines] + [scene.opening, scene.event or ""]
    return " ".join(parts)


def _future_texts(project: StoryProjectDef, turn: int) -> list[str]:
    texts: list[str] = []
    for scene in project.scenes[turn + 1 :]:
        texts += [l.text for l in scene.opening_lines + scene.follow_up_lines + scene.fixed_lines]
        texts += list(scene.system_messages)
        if not scene.opening_lines and scene.opening:
            texts.append(scene.opening.split("\n", 1)[-1])
    return [t for t in (_norm(x) for x in texts) if len(t) >= 10]


def validate_lines(
    project: StoryProjectDef,
    turn: int,
    lines: list[tuple[str, str]],
    previous_replies: list[str],
    nickname: str,
) -> list[Violation]:
    found: list[Violation] = []
    scene = project.scenes[turn]
    joined = " ".join(text for _, text in lines)
    visible = visible_texts_until(project, turn)
    is_last_input_scene = all(s.input_mode == "none" for s in project.scenes[turn + 1 :])

    for speaker, text in lines:
        spoken_sentences = sentences(text)
        polite = [s for s in spoken_sentences if POLITE_END.search(s)]
        if polite:
            found.append(Violation("style_polite", f"{speaker}: {polite[0][:30]}"))
        if len(spoken_sentences) > MAX_SENTENCES:
            found.append(Violation("too_many_sentences", f"{speaker}: {len(spoken_sentences)}문장", len(spoken_sentences)))
        if project.id == "cloud" and len(PAREN.findall(text)) > 1:
            found.append(Violation("stage_direction", f"{speaker}: 지문 {len(PAREN.findall(text))}개"))
        if project.id == "cloud" and speaker == "두두" and nickname and nickname in text and not is_last_input_scene:
            found.append(Violation("dudu_nickname", "마지막 장면 전 두두의 호칭 사용"))

    if any(word in joined for word in GENDER_ADDRESS) or _gendered_nickname(joined, nickname):
        found.append(Violation("forbidden_address", "성별을 가정하는 호칭"))
    unseen = [name for name in TENTATIVE_NAMES if name in joined and name not in visible]
    if unseen:
        found.append(Violation("tentative_name", ", ".join(unseen)))
    if project.id == "fridge":
        companies = [c for c in REAL_COMPANIES if c in joined]
        invest = [p for p in INVEST_PHRASES if p in joined]
        if companies or invest:
            found.append(Violation("real_finance", ", ".join(companies + invest)))
    if any(marker in joined for marker in LEAK_MARKERS) or "##" in joined:
        found.append(Violation("prompt_leak", "내부 규칙 표기"))
    normalized = _norm(joined)
    if any(f in normalized for f in _future_texts(project, turn)):
        found.append(Violation("future_scene", "이후 장면 문장"))
    references = [*previous_replies, scene.opening, *(l.text for l in scene.opening_lines)]
    for ref in references:
        ref_norm = _norm(ref)
        if ref_norm and normalized and (normalized == ref_norm or SequenceMatcher(None, normalized, ref_norm).ratio() >= REPEAT_RATIO):
            found.append(Violation("repetition", ref[:30]))
            break
    return found


def correction_note(violations: list[Violation]) -> str:
    labels = {
        "style_polite": "존댓말(~요/~습니다)을 썼다. 캐릭터 말투로 고친다.",
        "too_many_sentences": "문장이 3개를 넘었다. 1~3문장으로 줄인다.",
        "stage_direction": "대원 한 명에 지문이 둘 이상이다. 한 개까지만 쓴다.",
        "forbidden_address": "성별을 가정하는 호칭을 썼다.",
        "tentative_name": "화면에 나오지 않은 고유명사를 썼다.",
        "real_finance": "실존 기업·투자 표현을 썼다.",
        "prompt_leak": "내부 규칙 표현이 드러났다.",
        "future_scene": "이후 장면 내용을 미리 말했다. 현재 장면에 머문다.",
        "repetition": "이전 대사를 반복했다. 새로운 말로 답한다.",
        "dudu_nickname": "두두는 아직 사용자 호칭을 부르지 않는다.",
    }
    counts = [v.count for v in violations if v.code == "too_many_sentences" and v.count]
    if counts:
        # 원문 없이 숫자만 알려 준다. 판정 기준(감탄 포함·상한 MAX_SENTENCES)은 그대로다.
        labels["too_many_sentences"] = (
            f"문장이 {max(counts)}개였다. '흠흠.' 같은 짧은 감탄도 한 문장으로 센다. "
            f"{MAX_SENTENCES}문장 이하로 줄인다."
        )
    return " ".join(dict.fromkeys(labels.get(v.code, v.code) for v in violations))
