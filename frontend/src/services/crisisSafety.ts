// 위기 신호 안내 (기획서 FR-61, docs/stories/safety-notice-and-name-check.md)
// - 자해·자살처럼 자신을 해치려는 표현에만 반응한다. 일상적인 "힘들다"에는 반응하지 않는다.
// - 감지되면 AI를 부르지 않고(장난·홍보·장면 진행 중단) 그 문장을 서버로 보내지 않는다.
// - 캐릭터 반응은 AI가 만들지 않는 고정 문장이다. 진단·약속·저장 약속을 하지 않는다.
// - 감지 단어는 서버 backend/app/services/memory.py의 PURUMA_CRISIS_PATTERNS와 맞추고,
//   띄어쓰기 차이("죽고싶다")와 몇 가지 표현을 더 잡는다. 애매하면 안내하는 쪽을 택한다.

const CRISIS_PATTERNS = [
  '자살', '죽고싶', '죽어버리', '죽을래', '자해', '사라지고싶', '살기싫', '살고싶지않',
  '극단적선택', '목숨을끊', '스스로목숨', '뛰어내리고싶',
]

export function isCrisisText(text: string): boolean {
  const compact = (text ?? '').replace(/\s+/g, '')
  return CRISIS_PATTERNS.some(pattern => compact.includes(pattern))
}

export const CRISIS_NOTICE = {
  title: '도움이 필요할 때',
  lines: ['지금 많이 힘드신가요? 혼자 견디지 않아도 괜찮아요.'],
  contacts: [
    { label: '자살예방상담전화', number: '109', tel: 'tel:109', note: '24시간 언제든 이야기를 들어 드려요.' },
    { label: '위급한 상황', number: '119', tel: 'tel:119', note: '지금 위급하다면 바로 연락해 주세요.' },
  ],
} as const

export type CrisisProject = 'puruma' | 'fridge' | 'cloud'

// 안내 말풍선 뒤에 붙는 캐릭터의 짧은 반응. 장난·홍보·스토리 진행 없이 곁에 있어 주는 말만 한다.
export function crisisCareLine(project: CrisisProject): { speaker: string; text: string } {
  if (project === 'fridge') return { speaker: '냉장고 회장', text: '…자네, 그 번호로 꼭 이야기해 보게. 나는 여기 있겠네.' }
  if (project === 'cloud') return { speaker: '나나', text: '…말해 줘서 고마워. 위에 있는 번호, 꼭 눌러 봐. 우리 여기 있을게.' }
  return { speaker: '푸르마', text: '선배, 말해 줘서 고마워요. 위에 있는 번호로 꼭 이야기해 보세요. 저도 여기 있을게요.' }
}
