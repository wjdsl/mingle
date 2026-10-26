import type { Choice, TurnResponse } from '../../features/chat/types'

// 출처: docs/planning의 푸르마 기획서 v0.2 §3.2 개강.
// 두 번째 턴과 자유 입력 응답은 PM 검토 전 시연용 초안이다.
export const opening = '선배, 강의실이 어딘지 모르겠어요. 캠퍼스가 너무 넓어서 어디가 어딘지 모르겠어요.'
export const choices: Choice[][] = [
  [
    { id: 'map', label: '지도 같이 보자' },
    { id: 'ask', label: '사람들한테 물어보자' },
    { id: 'guide', label: '내가 데려다줄게' },
  ],
  [
    { id: 'quiet', label: '천천히, 조용히 들어가자' },
    { id: 'cheer', label: '괜찮아, 내가 옆에 있잖아' },
    { id: 'greet', label: '인사하고 들어가자' },
  ],
]
const nextScene = '\n강의실에 도착했는데 벌써 수업 중이에요… 뒷문으로 살금살금 들어가 볼까요?'
export const firstResponses: Record<string, TurnResponse> = {
  map: { text: '지도에 이렇게 나오는 거였구나! 이제 알겠어요.' + nextScene, emotion: 'sparkle' },
  ask: { text: '물어봐도 돼요? 저 낯을 가리는데… 선배가 먼저 말해 주세요.' + nextScene, emotion: 'confused' },
  guide: { text: '선배 믿고 따라갈게요! 앞장서 주세요.' + nextScene, emotion: 'happy' },
}
export const secondResponses: Record<string, TurnResponse> = {
  quiet: { text: '살금살금… 앗, 또각! 말발굽 소리가 나 버렸어요. 그래도 선배 덕분에 자리에 앉았어요, 히히힝!', emotion: 'sparkle' },
  cheer: { text: '선배가 옆에 있으니까 용기가 나요! 또각… 조금 시끄러웠지만 첫 수업에 무사히 들어왔어요, 히히힝!', emotion: 'happy' },
  greet: { text: '늦어서 죄송합니다…! 인사하고 들어오니까 마음이 놓여요. 선배, 첫 수업부터 정말 정신없네요!', emotion: 'happy' },
}
