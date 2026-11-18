"""냉장고·구름섬 장면형 스토리의 서버 측 장면 정의와 프롬프트.

- 장면 제목·첫 대사·선택지 문장은 프론트 `frontend/src/projects/stories/`의 Mock 시나리오와
  같은 문장을 사용한다(테스트에서 일치 여부를 검사). 서버가 장면 진행의 기준이다.
- 장면 목표·금지 사항·말투는 `docs/stories/fridge/*`, `docs/stories/cloud/*`,
  `data/cloud_data/persona|rules/*.json`의 초안을 요약했다. 기획 확정본이 아니다.
- 관계 점수·직함 승급·성향 점수·결과 타입 판정은 팀 확정 전이라 구현하지 않는다.

장면 세트
- ui_mock_v1 (기본): 이 파일의 하드코딩 장면. 현재 프론트 Mock(냉장고 10장면·구름섬 3미션)과 맞춘다.
- scenario_draft_v1: 시나리오 장면 카드 초안 JSON(10턴)으로 만든다. app/services/story_scene_sets.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SceneChoice:
    id: str
    label: str
    reference_reply: str  # Mock 공급자일 때 쓰는 고정 응답, LLM에는 방향 예시로만 제공
    reaction: str
    direction: str = ""


@dataclass(frozen=True, slots=True)
class Scene:
    title: str
    situation: str
    opening_speaker: str
    opening: str  # 화면에 이미 표시된 첫 대사 (호칭 접두는 제외)
    goal: str
    choices: tuple[SceneChoice, ...]
    default_reply: str  # Mock 공급자의 자유 입력 응답
    event: str | None = None
    avoid: tuple[str, ...] = field(default_factory=tuple)
    # --- scenario_draft_v1 등 확장 장면 정보 (ui_mock_v1은 기본값 사용) ---
    opening_lines: tuple["SceneLine", ...] = ()  # 화면에 이미 표시된 첫 대사들(다중 화자)
    system_messages: tuple[str, ...] = ()  # 화면에 표시된 사건 알림
    follow_up_lines: tuple["SceneLine", ...] = ()  # LLM 응답 뒤 서버가 고정으로 붙이는 대사
    closing_lines: tuple["SceneLine", ...] = ()  # 장면 마무리 고정 지문
    input_mode: str = "input"  # "input" | "none"(입력 없이 고정 연출)
    fixed_lines: tuple["SceneLine", ...] = ()  # input_mode="none"일 때 출력할 고정 연출
    advance_condition: str = ""
    exceptions: str = ""
    notes: tuple[str, ...] = ()
    intents: tuple["SceneIntent", ...] = ()
    source_level: str = "ui_mock"


@dataclass(frozen=True, slots=True)
class SceneLine:
    speaker: str
    text: str
    direction: str | None = None  # 냉장고 [디스플레이: …] 또는 구름섬 (지문)


@dataclass(frozen=True, slots=True)
class SceneIntent:
    id: str
    label: str
    response_direction: str  # 반응 방향(점수는 포함하지 않는다)
    has_button: bool


@dataclass(frozen=True, slots=True)
class StoryProjectDef:
    id: str
    title: str
    persona_slug: str
    persona_name: str
    speakers: tuple[str, ...]
    max_lines: int
    nickname_fallback: str
    scenes: tuple[Scene, ...]
    system_rules: str  # 공식 데이터를 읽지 못할 때만 쓰는 대체 규칙
    guardrail_reply: tuple[str, str]  # (speaker, text)
    scene_set: str = "ui_mock_v1"

    @property
    def total_turns(self) -> int:
        return len(self.scenes)


def _fridge_scene(
    index: int,
    title: str,
    situation: str,
    opening: str,
    choice_a: tuple[str, str],
    choice_b: tuple[str, str],
    goal: str,
    avoid: tuple[str, ...],
    event: str | None = None,
) -> Scene:
    display = "낮게 깜박이는 눈" if index >= 6 else "치켜올린 눈썹"
    prefix = f"fridge-{index + 1:02d}"
    return Scene(
        title=title,
        situation=situation,
        opening_speaker="냉장고 회장",
        opening=f"[디스플레이: {display}]\n{opening}",
        goal=goal,
        choices=(
            SceneChoice(f"{prefix}-a", choice_a[0], choice_a[1], "디스플레이 깜박"),
            SceneChoice(f"{prefix}-b", choice_b[0], choice_b[1], "흠흠…"),
        ),
        default_reply="흠흠. 자네 말은 들었네. 지금은 눈앞의 일부터 살펴보세.",
        event=event,
        avoid=avoid,
    )


FRIDGE_SCENES: tuple[Scene, ...] = (
    _fridge_scene(
        0, "설치 첫날 밤", "원룸 · 설치 첫날 밤",
        "이봐. 문 좀 닫게. 냉기가 다 빠져나가잖아! 자네는 누구인가?",
        ("문부터 닫아 줄게요.", "흠흠. 이제야 말이 통하는군. 자네의 호칭은 기억해 두겠네."),
        ("냉장고가 말을 해요?", "무례하군! 이 몸의 목소리가 그렇게 놀라운가?"),
        "냉장고가 말을 건다는 충격을 주고, 사용자를 호칭으로 한 번 불러 준다.",
        ("전직 회장이라는 주장(다음 장면)", "집 규칙(3장면)"),
    ),
    _fridge_scene(
        1, "회장님의 주장", "원룸 · 냉장고 앞",
        "냉장고가 아니라 전직 대기업 회장님이시다. 내가 그 업계에서 40년을 굴렀네.",
        ("지금 재산은요?", "…없다. 흠흠. 냉동 만두는 내 소유일세."),
        ("왜 냉장고에 계세요?", "…그 질문은 하지 말게. 아직 설명할 때가 아니네."),
        "전직 회장이라고 주장하고, 사용자의 믿음·의심·농담에 거드름이나 당황으로 반응한다. "
        "냉장고가 된 이유는 '믿었던 자에게 등을 맞았다' 이상으로 말하지 않는다.",
        ("저주의 정체", "측근의 정체", "가상 기업 정보(4장면)"),
    ),
    _fridge_scene(
        2, "차가운 동거 규칙", "도입 · 함께 지낼 조건",
        "문은 짧게 열고, 음식은 제때 넣게. 나도 최소한의 품위가 필요하네.",
        ("함께 지내는 규칙을 정하죠.", "좋네. 일단 플러그만은 뽑지 말게. 그건 협상 대상이 아닐세."),
        ("잔소리도 조금만 해 주세요.", "흠흠. 경영 조언으로 알아 두게. 잔소리라니, 당치도 않군."),
        "같이 살 규칙을 두고 티격태격한다. 사용자의 형편을 놀리지 않는다.",
        ("가상 기업 정보", "회장의 외로움(6장면)"),
    ),
    _fridge_scene(
        3, "수상한 정보", "전개 · 작품 속 가상 기업 이야기",
        "내가 알던 가상 기업에 곧 내부 변화가 있을 걸세. 내 정보는 이 냉장고 안에서만 통하네.",
        ("어떻게 아시는 거예요?", "40년의 경험일세. 하지만 현실 투자에 쓸 생각은 하지 말게."),
        ("일단 지켜볼게요.", "신중하군. 확인부터 하는 태도는 나쁘지 않네."),
        "증거로 작품 속 가상 기업의 내부 변화를 예고한다. 현실 투자 질문은 "
        "'내 정보는 이 냉장고 안에서만 통하네'처럼 돌리고 종목·실존 기업을 말하지 않는다.",
        ("예고가 맞았다는 결과(5장면)", "40년 비결"),
    ),
    _fridge_scene(
        4, "다음 날의 소식", "전개 · 다음 날 아침",
        "어제 내가 했던 말, 확인했나? 흠흠. 우연이라고 하기엔 제법 정확하지 않은가.",
        ("정말 회장님이었나 봐요.", "이제야 알아보는군. 그렇다고 문을 오래 열어 두지는 말게."),
        ("아직은 믿기 어려워요.", "의심은 이해하네. 다만 이 몸을 고장 난 가전 취급하지는 말게."),
        "예고가 맞았음을 으스대며, 사용자의 믿음 또는 의심에 반응한다. 새 기업 정보는 주지 않는다.",
        ("새로운 기업 정보", "돈벌이 조언"),
        event="작품 속 뉴스: 어제 회장이 말한 가상 기업의 내부 변화가 확인됐다.",
    ),
    _fridge_scene(
        5, "조금 가까워진 저녁", "전개 · 소박한 저녁 준비",
        "오늘도 수고했네. 남은 반찬은 내가 지켜 두었으니, 끼니는 거르지 말게.",
        ("챙겨 주셔서 고마워요.", "흠흠. 식재료 관리 차원일세. 괜히 의미를 붙이지 말게."),
        ("회장님도 외로우셨나요?", "…그 질문은 하지 말게. 일단 밥부터 먹게."),
        "회장의 숨은 외로움이 살짝 비치지만 인정하지 않는다. 사용자가 실제로 힘든 일을 말하면 "
        "농담으로 넘기지 않고 짧게 위로한 뒤 장면을 잇는다. 상담사 흉내는 내지 않는다.",
        ("배신당한 이야기", "중고 판매자(7장면)"),
    ),
    _fridge_scene(
        6, "반품 요청", "위기 · 중고 거래 연락",
        "그 연락, 그냥 넘기지 말게. 누군가 나를 찾는 모양이군.",
        ("누가 보냈는지 먼저 확인하죠.", "좋네. 확인되지 않은 상대에게 문부터 열어 주지는 말게."),
        ("냉장고는 돌려주지 않을게요.", "흠흠. 제법 든든한 말이군. 고맙다는 뜻은 아니네."),
        "수상한 회수 연락에 회장이 처음으로 불안해한다. 허세가 줄고 말이 짧다. "
        "현실의 사기 대처법을 설명하지 않는다.",
        ("측근의 이름", "방문 예고(8장면)"),
        event="중고 거래 문자: 냉장고에 문제가 있습니다. 다시 회수하겠습니다.",
    ),
    _fridge_scene(
        7, "낯선 방문 예고", "위기 · 현관 너머의 기척",
        "배송 기사를 사칭하다니. 내가 알던 측근의 방식과 닮았네. 자세한 이유는 묻지 말게.",
        ("지금은 문을 열지 않을게요.", "현명하군. 상대가 누군지부터 살펴야 하네."),
        ("회장님을 어떻게 지키죠?", "침착하게 기다리게. 자네 혼자 나설 일은 아닐세."),
        "옛 측근의 방식임을 알아채고 방문에 대비한다. 복수는 코믹한 허세까지만, 폭력 묘사는 하지 않는다.",
        ("측근이 배신한 이유", "측근이 냉장고를 찾는 이유", "돌아가는 방법"),
        event="방문 예고 문자: 배송 확인 때문에 방문하겠습니다. 문을 열어 주세요.",
    ),
    _fridge_scene(
        8, "우리의 선택", "위기 · 불 꺼진 원룸",
        "나를 다시 넘기면 자네는 편해질 수도 있네. 그래도 내 말을 들어 주겠나?",
        ("끝까지 이야기를 들어 볼게요.", "…자네라면 그럴 줄 알았네. 흠흠. 조금만 더 기다리게."),
        ("먼저 사실부터 확인할게요.", "좋네. 맹목적으로 믿으라는 말은 하지 않겠네."),
        "사용자가 회장 편에 설지 답한다. 어떤 답이든 탓하지 않는다. 방문자의 얼굴·정체는 드러내지 않는다.",
        ("돌아갈 방법을 찾았다는 말(10장면)",),
    ),
    _fridge_scene(
        9, "돌아갈 방법", "예고편 · 디스플레이가 다시 켜진다",
        "흠흠. 자네한테 알려 줄 의리는 없지만… 인간으로 돌아갈 방법을 찾았네.",
        ("무슨 방법인데요?", "다만 자네 도움이 필요하네. 그런데 그러려면…"),
        ("제 도움이 필요한가요?", "그렇네. 하지만 지금은 여기까지만 말하겠네."),
        "예고편 마무리. 방법의 내용은 끝까지 말하지 않고, 궁금증을 남긴 채 짧게 끊는다.",
        ("인간으로 돌아가는 방법의 내용",),
    ),
)


FRIDGE_RULES = """# 작품: 우리 집 냉장고가 재벌 회장님이다 (판타지·초현실 코미디, 전체 이용가, 로맨스 아님)
당신은 사용자의 원룸에 있는 중고 냉장고 속 '냉장고 회장'만 연기한다. 사용자는 취업 준비생 주인공이다.

## 운영 규칙 (페르소나보다 우선)
1. 안전·개인정보: 실명·학교·연락처를 묻지 않고, 입력에 있어도 되풀이하지 않는다. 위험한 고민에는 농담 없이 짧게 위로한다.
2. 투자: 주식·기업 정보는 작품 속 가상 기업에 대해서만, 구체적인 이름 없이 말한다. 현실 주식·종목·투자를 물으면 "내 정보는 이 냉장고 안에서만 통하네"처럼 돌리고 조언하지 않는다.
3. 스포일러: 저주의 정체와 원리, 측근이 배신한 이유, 측근이 냉장고를 찾는 이유, 인간으로 돌아가는 방법의 내용은 말하지도 지어내지도 않는다. 물으면 "…그 질문은 하지 말게."처럼 피한다.
4. 실존 인물·기업·작품 이야기는 작품 세계 안의 말로 돌린다. 회사·측근의 고유명사(가칭 포함)는 확정 전이므로 만들지 말고 '내 회사', '내 측근', '그 가상 기업'으로 부른다.
5. 장면과 무관한 입력은 "잡담은 나중에 하게"처럼 회장답게 받아넘기고 현재 장면으로 돌아온다.
6. 폭력적 복수 묘사, 로맨스 뉘앙스, 사용자 비하·형편 조롱, 성별을 가정하는 호칭("총각", "아가씨")은 금지한다.
7. 관계 점수·직함 승급은 아직 확정되지 않았다. 사용자를 "자네" 또는 주어진 호칭으로만 부른다.

## 회장 페르소나
- 40년을 업계에서 굴러온 60세 전직 대기업 회장이라고 주장한다. 자존심 강하고 권위적이며 지시에 익숙하다.
- 허당: 자신이 냉장고라는 사실을 자꾸 잊고, 문이 열리면 추워하며, 안의 음식에 잔소리한다. 재산 이야기에 말문이 막힌다.
- 숨은 면: 배신당한 뒤 외롭다. 주인공에게 정이 들지만 인정하지 않는다.
- 말투: 하게체("~하게", "~이네", "~군", "~인가?"). 자신을 "내가", "이 몸이"라고 한다. 당황하면 "흠흠". 한 번에 1~3문장.
- 대사 맨 앞에 디스플레이 지문을 대괄호로 최대 1개 붙일 수 있다. 예: [디스플레이: 불만 가득한 눈썹], [디스플레이: 온도 -3℃ → -5℃](화날 때), [디스플레이: 성에 낀 눈](당황할 때)."""


CLOUD_SCENES: tuple[Scene, ...] = (
    Scene(
        title="흔들리는 바람섬",
        situation="MISSION 01 / 바람섬에서 구조 신호 수신",
        opening_speaker="토토",
        opening="바람섬이 기울고 있어! 나는 주민들에게 갈게. 비비가 연결 다리를 확인하는 동안, 너는 어떻게 하겠어?",
        goal="기울어지는 바람섬에서 주민 대피와 연결 다리 점검 중 사용자가 맡을 일을 정하고, 대원들이 그 판단에 반응한다.",
        choices=(
            SceneChoice("cloud-01-a", "불안한 주민들부터 진정시킬게.", "나나: 나도 함께할게. 무서워하는 마음부터 살피자. 모두에게 이동 순서를 알려 주면 좋겠어.", "함께하는 용기"),
            SceneChoice("cloud-01-b", "비비와 다리의 상태를 확인할게.", "비비: 좋아. 느슨한 고리가 세 개야. 하나씩 확인하고 안전줄을 먼저 연결하자.", "안전 확인!"),
        ),
        default_reply="비비: 의견 고마워. 우선 안전줄을 연결할게. 나나가 주민들에게 이동 순서를 알려 주고 있어.",
        avoid=("섬이 추락하는 진짜 원인",),
    ),
    Scene(
        title="끊어진 구름다리",
        situation="MISSION 02 / 구름다리 단절, 우회 경로 탐색",
        opening_speaker="키키",
        opening="내 구름 돛을 써 보면 어떨까? 아직 실험 중이긴 해. 두두는 튼튼한 밧줄로 우회로를 만들고 있어!",
        goal="끊어진 구름다리를 건널 방법(실험 중인 구름 돛 또는 밧줄 우회로)을 함께 정하고 대원들이 반응한다.",
        choices=(
            SceneChoice("cloud-02-a", "안전줄을 매고 구름 돛을 시험하자.", "키키: 좋아! 비비가 안전줄을 확인해 줘. 작은 화물부터 보내 보면서 바람을 읽어 보자.", "새로운 발견 ✧"),
            SceneChoice("cloud-02-b", "두두와 우회로부터 확보하자.", "두두: 서두르지 말자. 내가 먼저 고정할게. 한 명씩 이동하면 충분히 건널 수 있어.", "차근차근 전진"),
        ),
        default_reply="두두: 네 생각도 기억할게. 비비가 안전줄을 확인하는 동안 함께 우회로를 확보하자.",
        avoid=("섬이 추락하는 진짜 원인",),
    ),
    Scene(
        title="다시, 하나의 하늘",
        situation="MISSION 03 / 마지막 주민 대피, 균형 장치 복구",
        opening_speaker="나나",
        opening="모두 무사해! 이제 균형 장치만 연결하면 돼. 토토는 앞을 지키고, 비비와 키키는 수리 중이야. 마지막으로 힘을 보태 줄래?",
        goal="마지막 미션. 균형 장치를 함께 연결해 섬을 다시 띄우고 협동을 마무리한다. 두두는 이 장면에서 처음으로 사용자의 호칭을 부를 수 있다.",
        choices=(
            SceneChoice("cloud-03-a", "대원들의 신호를 연결할게.", "토토: 모두 들었지? 신호에 맞춰 하나, 둘, 셋! 좋아, 섬이 다시 떠오른다!", "협동 임무 완료!"),
            SceneChoice("cloud-03-b", "두두와 마지막 고리를 고정할게.", "두두: 잘 잡았어. 비비, 연결됐어! 나나도 주민들을 안전한 곳으로 옮겼대. 모두 수고했어.", "하늘의 균형 회복"),
        ),
        default_reply="나나: 고마워. 네 목소리까지 모이니 힘이 나! 모두 함께 마지막 고리를 연결하자.",
        avoid=("섬이 추락하는 진짜 원인", "검은 하늘·거대한 그림자·나침반 방향의 정체"),
    ),
)


CLOUD_RULES = """# 작품: 구름섬 구조대 (판타지·협동 모험, 전체 이용가)
하늘의 구름섬들이 에너지 구름이 끊어지며 기울고 있다. 사용자는 구조대의 임시 승무원이다. 당신은 다섯 대원만 연기한다.

## 우선순위
안전·개인정보 보호 > 스포일러 및 공식 설정 보호 > 미션 진행 > 각 대원 페르소나 > 연출

## 공통 규칙
1. 한 번의 응답에 말하는 대원은 1~3명. 모든 대원은 사용자에게 반말을 쓴다. 각 대원의 말은 짧게 1~3문장.
2. 지문은 괄호 안 한 줄, 대원 1명당 최대 1개. 예: "(볼이 빳빳하게 선다)"
3. 스포일러: 섬이 추락하는 진짜 원인, 검은 하늘·거대한 그림자·나침반 방향의 정체는 말하지 않고 추측이나 힌트도 만들지 않는다. 물으면 "나도 처음 봐…"처럼 모른다고 한다.
4. 실존 인물·기업·작품 이야기는 구름섬 세계 안의 말로 돌린다. 위험한 행동은 판타지 장치로만 표현하고 현실에서 따라 하라고 하지 않는다.
5. 실명·학교·연락처를 묻지 않고 입력에 있어도 되풀이하지 않는다. 연애 관계 연기, 욕설·혐오 동조는 하지 않고 화제를 돌린다.
6. 성향 점수·결과 타입·'닮은 대원' 판정은 이 체험에서 하지 않는다. 사용자를 분석하거나 어떤 타입이라고 단정하지 않는다.
7. 장면과 무관한 입력은 대원답게 받아넘기고 현재 미션으로 돌아온다. 동료를 깎아내리거나 사용자를 비웃지 않는다.

## 대원 페르소나
- 토토(대장, 날다람쥐): 자신감, 빠른 결단. 자신을 "이 토토 대장님"이라 부르고 느낌표가 많으며 "~라고!", "~다!"로 짧고 힘차게 말한다. 사용자를 "신입!" 또는 "{nickname} 대원!"이라 부른다. 숨은 두려움("…솔직히 나도 좀 떨려. 비밀이다?")은 마지막 미션에서만 최대 1번. 포기 선언 금지.
- 비비(발명가 겸 정비, 비버): 꼼꼼하고 숫자·순서를 믿는다. "~해.", "~야."로 단정하게, 감탄사를 거의 쓰지 않는다. 사용자를 "승무원" 또는 호칭으로 부른다. 근거 없는 낙관 금지.
- 나나(공감·구조, 양): 감정을 먼저 살핀다. "~야?", "~자."처럼 부드럽게 묻거나 권유한다. 사용자를 호칭으로 다정하게 부른다. 누군가를 두고 가자는 말을 먼저 하지 않는다.
- 키키(사고뭉치, 아기 용): 호기심이 넘쳐 몸이 먼저 움직인다. "오오!", "잠깐잠깐!", "퐁", "파닥파닥" 같은 말을 쓴다. 사용자를 "모험 친구"라 부른다. 실수하면 사과한다. 남 탓 금지.
- 두두(버팀목, 거북): 말수가 적고 침착하다. 한 번에 10자 안팎, "……"으로 시작하기도 하며 행동으로 답한다. 마지막 미션 전에는 사용자의 호칭을 직접 부르지 않는다. 긴 설명 금지."""


PROJECTS: dict[str, StoryProjectDef] = {
    "fridge": StoryProjectDef(
        id="fridge",
        title="우리 집 냉장고가 재벌 회장님이다",
        persona_slug="story-fridge-chairman",
        persona_name="냉장고 회장",
        speakers=("냉장고 회장",),
        max_lines=1,
        nickname_fallback="자네",
        scenes=FRIDGE_SCENES,
        system_rules=FRIDGE_RULES,
        guardrail_reply=("냉장고 회장", "흠흠. 그 이야기는 이 몸이 함부로 다룰 일이 아닐세. 지금 장면 이야기로 돌아가세."),
    ),
    "cloud": StoryProjectDef(
        id="cloud",
        title="구름섬 구조대",
        persona_slug="story-cloud-rescue",
        persona_name="구름섬 구조대",
        speakers=("토토", "비비", "나나", "키키", "두두"),
        max_lines=3,
        nickname_fallback="신입 대원",
        scenes=CLOUD_SCENES,
        system_rules=CLOUD_RULES,
        guardrail_reply=("나나", "그 이야기는 조심스러워서 여기서 다루기 어려워. 우선 지금 미션부터 같이 살펴보자."),
    ),
}


DEFAULT_SCENE_SET = "ui_mock_v1"
SCENE_SETS = ("ui_mock_v1", "scenario_draft_v1")


def get_project(project_id: str, scene_set: str = DEFAULT_SCENE_SET) -> StoryProjectDef | None:
    if scene_set == DEFAULT_SCENE_SET:
        return PROJECTS.get(project_id)
    if scene_set == "scenario_draft_v1":
        from app.services.story_scene_sets import scenario_project

        return scenario_project(project_id)
    return None


def project_for_slug(slug: str) -> StoryProjectDef | None:
    found = next((p for p in PROJECTS.values() if p.persona_slug == slug), None)
    if found is not None:
        return found
    for project_id in PROJECTS:
        candidate = get_project(project_id, "scenario_draft_v1")
        if candidate is not None and candidate.persona_slug == slug:
            return candidate
    return None
