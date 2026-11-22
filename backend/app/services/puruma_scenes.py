"""푸르마 10턴 장면 세트 (puruma_draft_v1, /api/story-chat 전용).

10턴 배치(2026-11-22 승인안 C): 개강 1-2 / 적응 3-4 / 중간고사 5-6 / 축제 7-8 / 기말·종강 9 / 방학 계획 10.
기획서(docs/푸르마_프로젝트_기획서.md)는 6구간·12턴이다. 축제를 3→2턴, 방학 계획을 2→1턴으로 줄였다.

문장 출처 구분
- `src="plan"`: 기획서 3.2·3.3장 문장을 글자 그대로 옮긴 것(고정 SOS, 선택지, 반응 예시, 전환 문구, 인용 대사).
  tests/test_puruma_story.py가 기획서 원문에 그대로 있는지 검사한다.
- `src="draft"`: 기획서에 없는 구현 초안(2026-11-22, 기획·팀 검토 전). 각 구간의 둘째 턴 장면, 10턴 반응,
  자유 입력용 고정 대사, CC·번아웃 덧붙임 대사가 여기에 해당한다.
- 장면 카드를 data/에 두지 않은 이유: data/validate_story_outlines.py는 장면 카드 문장이 시나리오 원문에 있는지
  검사하는데 푸르마에는 그런 시나리오 원문 문서가 없고 대사 상당수가 초안이다.

선택지 문장·첫 대사는 프론트 Mock(frontend/src/projects/puruma/scenes.ts)과 같은 문장을 쓴다(테스트로 일치 검사).
사용자 호칭은 "선배"로 쓰고 화면이 사용자가 정한 호칭으로 바꿔 표시한다(기존 푸르마 화면과 같다).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.services.story_scenes import Scene, SceneChoice, SceneIntent, SceneLine, StoryProjectDef

PURUMA_PROJECT = "puruma"
PURUMA_SCENE_SET = "puruma_draft_v1"
PURUMA_STORY_SLUG = "puruma-story-v1"
SPEAKER = "푸르마"
EMOTIONS = ("confused", "happy", "sparkle")
ATTITUDES = ("응원·도움", "중립", "퉁명·부정")
STATS = ("탐구", "기술", "예술", "소통", "글로벌")


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    title: str
    turns: tuple[int, ...]  # 0부터 시작하는 턴 번호
    promo_ids: tuple[str, ...]  # 이 구간에서 노출할 수 있는 RAG id (기획서 7장 R1~R3)


SECTIONS: tuple[Section, ...] = (
    Section("s1_opening", "개강", (0, 1), ()),
    Section("s2_adaptation", "적응", (2, 3), ("rag_dining_cafeteria_menu", "rag_clubs_yu_general_union")),
    Section("s3_midterm", "중간고사", (4, 5), ("rag_library_central",)),
    Section("s4_festival", "축제", (6, 7), ()),
    Section("s5_final", "기말·종강", (8,), ()),
    Section("s6_vacation_plan", "방학 계획", (9,), (
        "rag_career_center", "rag_international_office", "rag_student_life_yutopia", "rag_startup_incubation",
    )),
)


def section_of(turn: int) -> Section:
    return next(s for s in SECTIONS if turn in s.turns)


def is_sos_turn(turn: int) -> bool:
    """구간의 첫 턴은 고정 SOS 턴이다(기획서 3.1). SOS에 답하면 친밀도 +5."""
    return section_of(turn).turns[0] == turn


@dataclass(frozen=True, slots=True)
class ChoiceSpec:
    id: str
    label: str
    stat: str | None
    reply: str  # 반응 예시. Mock·AI 실패 시 고정 대사, LLM에는 방향 예시
    emotion: str
    promo: str | None = None
    path: str | None = None  # 10턴 진로 (엔딩 판정용)
    src: str = "plan"
    reply_src: str = "plan"


@dataclass(frozen=True, slots=True)
class TurnSpec:
    title: str
    situation: str
    opening: str
    opening_src: str
    goal: str
    choices: tuple[ChoiceSpec, ...]
    free_reply: str  # 자유 입력용 고정 대사(구현 초안)
    free_emotion: str
    avoid: tuple[str, ...] = ()


# 기획서 3.3 구간 전환 한마디
TRANSITIONS = {
    2: "여기가 강의실이었어요! 이제 점심이 궁금해요.",
    4: "벌써 시험이래요... 시간이 너무 빨라요.",
    6: "시험 끝났다! 이제 축제만 남았어요!",
    8: "축제 정말 즐거웠어요. 근데 이제 성적이...",
    9: "한 학기가 끝났어요. 선배 덕분이에요.",
}

# 기획서 3.2 고정 SOS
SOS = {
    0: "선배, 강의실이 어딘지 모르겠어요. 캠퍼스가 너무 넓어서 어디가 어딘지 모르겠어요.",
    2: "선배, 저 이 학교를 아직 잘 몰라요. 선배가 아는 것 중에 좋은 거, 재미있는 거 아무거나 추천해 주세요!",
    4: "선배, 중간고사가 코앞인데 아직 아무것도 못 했어요... 어디서 공부하면 좋을까요? 중앙도서관이 좋다던데, 자리가 있을까요?",
    6: "선배! 축제래요! 어디서 노래도 나고 맛있는 냄새도 나요! 저 선배랑 같이 가고 싶어요!",
    8: "선배... 성적이 무서워요. 장학금은 받을 수 있을까요?",
    9: "선배, 이제 방학이에요. 저... 이제 뭘 해야 하는지 모르겠어요. 진로도 정해야 할 것 같고요. 선배는 어떻게 생각해요?",
}


def _sos_opening(turn: int) -> str:
    return f"{TRANSITIONS[turn]}\n{SOS[turn]}" if turn in TRANSITIONS else SOS[turn]


TURNS: tuple[TurnSpec, ...] = (
    TurnSpec(
        title="개강 · 강의실 찾기",
        situation="첫 수업 날, 넓은 캠퍼스에서 길을 잃은 푸르마",
        opening=_sos_opening(0), opening_src="plan",
        goal="길을 잃은 푸르마가 선배의 답에 반응한다. 강의실·건물 위치나 학교 정보는 말하지 않는다.",
        choices=(
            ChoiceSpec("c1_t1_a", "지도 같이 보자", "탐구", "지도에 이렇게 나오는 거였구나! 이제 알겠어요.", "sparkle"),
            ChoiceSpec("c1_t1_b", "사람들한테 물어보자", "소통", "물어봐도 돼요? 저 낯을 가리는데... 선배가 먼저 말해 주세요.", "confused"),
            ChoiceSpec("c1_t1_c", "내가 데려다줄게", None, "선배 믿고 따라갈게요! 앞장서 주세요.", "happy"),
        ),
        free_reply="선배, 이야기해 줘서 고마워요! 우선 강의실부터 같이 찾아가 봐요.",
        free_emotion="happy",
        avoid=("수업이 이미 시작된 상황(다음 턴)",),
    ),
    TurnSpec(
        title="개강 · 첫 수업 소동",
        situation="겨우 강의실 앞에 도착했는데 수업이 이미 시작됐다",
        opening="강의실에 도착했는데 벌써 수업 중이에요... 뒷문으로 살금살금 들어가 볼까요?", opening_src="draft",
        goal="뒷문으로 살금살금 들어가다 말발굽 소리(또각)를 내 버리는 소동을 선배의 답에 맞춰 함께 겪는다.",
        choices=(
            ChoiceSpec("c1_t2_a", "천천히, 조용히 들어가자", None, "살금살금... 앗, 또각! 말발굽 소리가 나 버렸어요. 그래도 선배 덕분에 자리에 앉았어요, 히히힝!", "sparkle", src="draft", reply_src="draft"),
            ChoiceSpec("c1_t2_b", "괜찮아, 내가 옆에 있잖아", None, "선배가 옆에 있으니까 용기가 나요! 또각... 조금 시끄러웠지만 첫 수업에 무사히 들어왔어요, 히히힝!", "happy", src="draft", reply_src="draft"),
            ChoiceSpec("c1_t2_c", "인사하고 들어가자", None, "늦어서 죄송합니다...! 인사하고 들어오니까 마음이 놓여요. 선배, 첫 수업부터 정말 정신없네요!", "happy", src="draft", reply_src="draft"),
        ),
        free_reply="선배 말을 들으니 조금 안심돼요. 살금살금... 또각! 그래도 무사히 자리에 앉았어요.",
        free_emotion="sparkle",
        avoid=("점심·학교 추천(다음 구간)",),
    ),
    TurnSpec(
        title="적응 · 학교 추천받기",
        situation="첫 주가 지난 점심시간, 학교가 아직 낯선 푸르마",
        opening=_sos_opening(2), opening_src="plan",
        goal="정보를 말하는 쪽은 선배다. 선배의 추천을 천마다운 엉뚱한 반응으로 받아 준다. 도서관은 다음 구간에서 다룬다.",
        choices=(
            ChoiceSpec("c2_t3_a", "맛있는 밥", None, "선배가 추천하면 믿고 먹을게요! 저 풀만 먹는 거 아니에요, 히히힝.", "happy", promo="rag_dining_cafeteria_menu"),
            ChoiceSpec("c2_t3_b", "같이할 사람, 동아리", "소통", "사람이 막 모여 있는 곳이요? 선배랑 같이 가면 안 무서워요.", "happy", promo="rag_clubs_yu_general_union"),
            ChoiceSpec("c2_t3_c", "공부하기 좋은 곳", "탐구", "공부요...? 일단 메모해 둘게요. 시험 전에 꺼내 볼게요.", "confused"),
            ChoiceSpec("c2_t3_d", "구경하기 좋은 것", "예술", "와, 그런 것도 있어요? 저 구경은 자신 있어요!", "sparkle"),
        ),
        free_reply="오, 그런 것도 있군요! 선배 추천이라 더 궁금해져요.",
        free_emotion="sparkle",
        avoid=("중간고사·도서관(다음 구간)",),
    ),
    TurnSpec(
        title="적응 · 위시리스트",
        situation="선배의 추천을 받아 적고 더 알려 달라고 조르는 푸르마",
        opening="선배 추천, 한 학기 위시리스트에 넣었어요! 또 뭐 없어요? 하나만 더 알려 주세요!", opening_src="draft",
        goal="선배의 추천을 웃기게 받아 적고 더 알려 달라고 조른다.",
        choices=(
            ChoiceSpec("c2_t4_a", "점심은 학식 어때?", None, "학식이요? 말도 먹을 수 있는 메뉴가 있으면 좋겠어요!", "happy", promo="rag_dining_cafeteria_menu", src="draft", reply_src="draft"),
            ChoiceSpec("c2_t4_b", "동아리 구경도 해 봐", None, "동아리 구경이요? 선배가 같이 가 주면 용기 낼게요!", "happy", promo="rag_clubs_yu_general_union", src="draft", reply_src="draft"),
            ChoiceSpec("c2_t4_c", "천천히 둘러봐도 돼", None, "맞아요, 서두르지 않을게요. 선배 말 들으니까 마음이 편해요.", "happy", src="draft", reply_src="draft"),
        ),
        free_reply="그것도 위시리스트에 넣을게요! 히히힝, 벌써 한 줄이 꽉 찼어요.",
        free_emotion="sparkle",
        avoid=("중간고사·도서관(다음 구간)",),
    ),
    TurnSpec(
        title="중간고사 · 공부할 곳",
        situation="시험 2주 전, 도서관 앞",
        opening=_sos_opening(4), opening_src="plan",
        goal="시험 걱정을 선배와 나눈다. 좌석 현황이나 운영 시간은 모르므로 지어내지 않는다.",
        choices=(
            ChoiceSpec("c3_t5_a", "도서관 가서 같이 공부하자", "탐구", "같이 가 주시면 힘이 나요! 오늘은 끝까지 해 볼게요.", "sparkle", promo="rag_library_central"),
            ChoiceSpec("c3_t5_b", "스터디를 만들어 보자", "소통", "스터디요? 친구를 사귈 수 있겠어요!", "happy", promo="rag_library_central"),
            ChoiceSpec("c3_t5_c", "쉬면서 해", None, "맞아요, 무리하면 머리가 터질 것 같아요.", "happy"),
        ),
        free_reply="선배 말 듣고 나니 조금 덜 막막해요. 일단 오늘 할 것부터 정해 볼게요.",
        free_emotion="happy",
        avoid=("축제(다음 구간)",),
    ),
    TurnSpec(
        title="중간고사 · 공부하다 쉬는 시간",
        situation="책을 펴 놓으면 자꾸 눈이 감기는 푸르마",
        opening="선배, 공부하다가 잠깐 쉬는 중이에요. 책을 펴 놓으면 자꾸 눈이 감겨요... 어떻게 하면 집중이 잘 돼요?", opening_src="draft",
        goal="공부 고민에 짧게 공감하고 선배의 방법에 반응한다. 일상적인 힘듦이며 위기 상황처럼 대하지 않는다.",
        choices=(
            ChoiceSpec("c3_t6_a", "같이 계획 세워 보자", None, "계획표요? 선배랑 짜면 저도 지킬 수 있을 것 같아요!", "sparkle", src="draft", reply_src="draft"),
            ChoiceSpec("c3_t6_b", "잠깐 산책하고 오자", None, "산책 좋아요! 다리를 좀 풀면 머리도 맑아질 것 같아요, 히히힝.", "happy", src="draft", reply_src="draft"),
            ChoiceSpec("c3_t6_c", "오늘은 일찍 자", None, "일찍 자는 것도 공부래요? 선배 말이면 믿어 볼게요.", "happy", src="draft", reply_src="draft"),
        ),
        free_reply="선배 방법대로 해 볼게요. 조금씩이라도 하면 되겠죠?",
        free_emotion="happy",
        avoid=("축제(다음 구간)",),
    ),
    TurnSpec(
        title="축제 · 어디부터 갈까",
        situation="축제 기간, 들떠 있는 캠퍼스",
        opening=_sos_opening(6), opening_src="plan",
        goal="선배와 축제를 즐긴다. 이 구간에는 홍보가 없다.",
        choices=(
            ChoiceSpec("c4_t7_a", "공연부터 보자", "예술", "노래가 막 울려요! 저도 몸이 들썩들썩해요, 히히힝!", "sparkle"),
            ChoiceSpec("c4_t7_b", "푸드트럭부터 가자", "소통", "줄이 엄청 길어요! 근데 냄새가 너무 좋아서 기다릴 수 있어요.", "happy"),
            ChoiceSpec("c4_t7_c", "너 혼자 다녀와", None, "저 혼자요...? 용기를 내 볼게요. 다녀올게요!", "confused"),
        ),
        free_reply="선배랑 축제라니 벌써 신나요! 어디부터 갈지 같이 골라요.",
        free_emotion="sparkle",
        avoid=("기말·성적(다음 구간)",),
    ),
    TurnSpec(
        title="축제 · 푸드트럭과 공연",
        situation="공연이 시작되기 전, 푸드트럭 메뉴 앞",
        opening="선배, 저기 무대에서 곧 공연이 시작한대요! 그 전에 뭐 좀 먹을까요? 근데... 말이 먹어도 되는 걸까요?", opening_src="draft",
        goal="메뉴 앞에서 고민하는 개그를 하고 선배와 공연을 즐기며 구간을 마친다.",
        choices=(
            ChoiceSpec("c4_t8_a", "이거 먹어 봐", None, "선배가 골라 주는 거면 믿고 먹을게요! 음, 맛있어요!", "happy", src="draft", reply_src="draft"),
            ChoiceSpec("c4_t8_b", "같이 공연 보면서 먹자", None, "좋아요! 노래 들으면서 먹으니까 더 맛있어요. 이 시간이 오래갔으면 좋겠어요.", "sparkle", src="draft", reply_src="draft"),
            ChoiceSpec("c4_t8_c", "천천히 골라도 돼", None, "히히힝, 고민하는 것도 축제의 재미 같아요. 선배는 뭐 먹을 거예요?", "happy", src="draft", reply_src="draft"),
        ),
        free_reply="선배 덕분에 축제가 더 즐거워요. 이 시간이 오래갔으면 좋겠어요.",
        free_emotion="sparkle",
        avoid=("기말·성적(다음 구간)",),
    ),
    TurnSpec(
        title="기말·종강 · 성적 걱정",
        situation="종강이 다가오고 성적이 걱정되는 시기",
        opening=_sos_opening(8), opening_src="plan",
        goal="성적 걱정에 공감한다. 장학금·성적 기준을 단정하지 않는다. 이 구간에는 홍보가 없다.",
        choices=(
            ChoiceSpec("c5_t9_a", "막판 스퍼트하자", "탐구", "알겠어요, 끝까지 달려 볼게요!", "sparkle"),
            ChoiceSpec("c5_t9_b", "계획을 세워 보자", "소통", "계획표요? 선배가 짜 주는 거면 믿고 따를게요.", "happy"),
            ChoiceSpec("c5_t9_c", "응원만 할게", None, "응원만으로도 힘이 나요, 고마워요 선배.", "happy"),
        ),
        free_reply="선배 말 들으니까 조금 덜 무서워요. 끝까지 해 볼게요.",
        free_emotion="happy",
        avoid=("방학·진로(다음 구간)",),
    ),
    TurnSpec(
        title="방학 계획 · 진로 고민",
        situation="종강 후, 앞으로의 길을 고민하는 푸르마",
        opening=_sos_opening(9), opening_src="plan",
        goal="선배가 권한 길에 대한 푸르마의 다짐으로 한 학기를 마무리한다. 엔딩은 화면이 따로 보여 준다.",
        choices=(
            ChoiceSpec("c6_t10_a", "취업 준비를 해 보자", "소통", "취업 준비요? 저도 그쪽이 궁금했어요. 같이 알아봐요.", "sparkle", promo="rag_career_center", path="career", reply_src="draft"),
            ChoiceSpec("c6_t10_b", "교환학생을 알아보자", "글로벌", "교환학생이요? 저도 그쪽이 궁금했어요. 같이 알아봐요.", "sparkle", promo="rag_international_office", path="exchange", reply_src="draft"),
            ChoiceSpec("c6_t10_c", "비교과 활동을 해 보자", "소통", "비교과 활동이요? 저도 그쪽이 궁금했어요. 같이 알아봐요.", "sparkle", promo="rag_student_life_yutopia", path="extracurricular", reply_src="draft"),
            ChoiceSpec("c6_t10_d", "창업을 해 보자", "기술", "창업이요? 저도 그쪽이 궁금했어요. 같이 알아봐요.", "sparkle", promo="rag_startup_incubation", path="startup", reply_src="draft"),
        ),
        free_reply="선배 이야기 들으니까 방학이 기대돼요. 저만의 길, 천천히 찾아볼게요.",
        free_emotion="sparkle",
    ),
)

# 10턴 자유 입력의 진로: 홍보 링크와 같은 키워드 판정 결과(RAG id)로 정한다.
PROMO_PATH = {
    "rag_career_center": "career",
    "rag_international_office": "exchange",
    "rag_student_life_yutopia": "extracurricular",
    "rag_startup_incubation": "startup",
}

# 자유 입력 주제(기획서 5.2, data/rules/pruma_topic_classification.json의 6개 주제). LLM이 intent_id로 분류한다.
TOPIC_INTENTS: tuple[tuple[str, str, str | None], ...] = (
    ("topic_study", "탐구: 공부·연구·학업", "탐구"),
    ("topic_tech", "기술: 만들기·코딩·창업", "기술"),
    ("topic_art", "예술: 공연·창작·문화", "예술"),
    ("topic_social", "소통: 사람 만나기·동아리·진로·대외활동", "소통"),
    ("topic_global", "글로벌: 외국어·교환학생·국제", "글로벌"),
    ("topic_daily", "일상: 위 어디에도 뚜렷하지 않거나 여러 주제가 섞임", None),
)
TOPIC_STAT = {intent_id: stat for intent_id, _, stat in TOPIC_INTENTS}

# 조건부 덧붙임 대사 (구현 초안, CC 미귀환 대사만 기획서 인용)
CC_SEED_LINE = "(잠시 뒤, 얼굴이 빨개져서 돌아왔다) 서, 선배... 푸드트럭 줄에서 어떤 분이랑 나란히 서 있었는데... 아, 아무것도 아니에요!"
SOLO_RETURN_LINE = "(잠시 뒤, 시무룩하게 돌아왔다) 선배랑 같이 먹을 걸 그랬어요."
BURNOUT_LINE = "...근데 선배, 요즘 책상 앞에만 있다 보니 잠을 잘 못 자요..."
NEAR_MISS_LINE = "그래도... 한 걸음만 더 갔으면 됐는데. 다음엔 꼭 해낼 거예요!"

GUARDRAIL_REPLY = (SPEAKER, "그 이야기는 제가 함부로 다루기 어려워요... 선배, 우리 다시 학교 이야기 해요!")

CHOICES: dict[str, ChoiceSpec] = {c.id: c for spec in TURNS for c in spec.choices}


def choice_turn(choice_id: str) -> int | None:
    return next((i for i, spec in enumerate(TURNS) if any(c.id == choice_id for c in spec.choices)), None)


def _scene(index: int, spec: TurnSpec) -> Scene:
    return Scene(
        title=spec.title,
        situation=spec.situation,
        opening_speaker=SPEAKER,
        opening=spec.opening,
        goal=spec.goal,
        choices=tuple(SceneChoice(c.id, c.label, c.reply, "", "") for c in spec.choices),
        default_reply=spec.free_reply,
        avoid=spec.avoid,
        opening_lines=(SceneLine(SPEAKER, spec.opening),),
        intents=tuple(SceneIntent(i, label, "선배의 이야기에 장면에 맞게 반응한다", False) for i, label, _ in TOPIC_INTENTS),
        source_level="puruma_draft",
    )


@lru_cache(maxsize=1)
def puruma_project() -> StoryProjectDef:
    return StoryProjectDef(
        id=PURUMA_PROJECT,
        title="푸르마와 학교 다니기",
        persona_slug=PURUMA_STORY_SLUG,
        persona_name="푸르마 (10턴 장면 초안)",
        speakers=(SPEAKER,),
        max_lines=1,
        nickname_fallback="선배",
        scenes=tuple(_scene(i, spec) for i, spec in enumerate(TURNS)),
        system_rules="",  # 규칙은 story_prompt.puruma_rules()가 seed_puruma 원문 문장으로 만든다.
        guardrail_reply=GUARDRAIL_REPLY,
        scene_set=PURUMA_SCENE_SET,
    )
