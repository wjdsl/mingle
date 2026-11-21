// 냉장고·구름섬 위기 신호 안내 (기획 초안: docs/stories/safety-notice-and-name-check.md 1장, 팀 확정 전).
// 자유 입력에 자신을 해치려는 표현이 있으면 서버·LLM에 보내지 않고 이 안내를 대화 안의 시스템 말풍선으로 띄운다.
// 번호·문구는 이 파일 한 곳에서만 관리한다. 백엔드 패턴(story_safety.py)과 같은 목록을 유지한다.

const PATTERNS = [
  '자살', '죽고싶', '죽어버리', '죽을래', '자해', '사라지고싶', '살기싫', '살고싶지않',
  '다끝내고싶', '끝내버리고싶', '목숨을끊', '생을마감', '세상을떠나고싶',
]

// 판단이 애매하면 안내하는 쪽을 택한다. 공백을 모두 지운 뒤 포함 여부만 본다.
export function isCrisisText(text: string): boolean {
  const squashed = text.replace(/\s+/g, '')
  return PATTERNS.some(pattern => squashed.includes(pattern))
}

export type SafetyNoticeLine = { text: string; strong?: boolean; href?: string }
// 캐릭터 대사가 아니라 서비스 시스템 문구다. 캐릭터 말투를 쓰지 않는다.
export const SAFETY_NOTICE: SafetyNoticeLine[][] = [
  [{ text: '지금 많이 힘드신가요? 혼자 견디지 않아도 괜찮아요.' }],
  [{ text: '24시간 언제든 ' }, { text: '자살예방상담전화 ☎109', strong: true, href: 'tel:109' }, { text: '에서 이야기를 들어 드려요.' }],
  [{ text: '지금 위급한 상황이라면 ' }, { text: '☎119', strong: true, href: 'tel:119' }, { text: '로 바로 연락해 주세요.' }],
]

// 안내 뒤 캐릭터 반응: 장난·홍보·진행 없이 곁에 있어 주는 말만 한다(진단·약속·저장 약속·다음 장면 유도 금지).
const COMPANION: Record<string, { speaker: string; text: string }> = {
  fridge: { speaker: '냉장고 회장', text: '…자네, 그 번호로 꼭 이야기해 보게. 나는 여기 있겠네.' },
  cloud: { speaker: '나나', text: '…말해 줘서 고마워. 위에 있는 번호, 꼭 눌러 봐.' },
}
export function companionLine(projectId: string): { speaker: string; text: string } | undefined {
  return COMPANION[projectId]
}
