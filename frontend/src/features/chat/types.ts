export type Emotion = 'confused' | 'happy' | 'sparkle'
export type Choice = { id: string; label: string }
// 홍보 링크 카드(서버가 확인된 공식 URL이 있는 항목만 보낸다). 새 탭으로 연다.
export type Promo = { id: string; label: string; url: string; sourceName: string }
// role 'notice'는 위기 안내 시스템 말풍선. calm은 장난스러운 리액션 문구·기호를 붙이지 않는 캐릭터 대사.
export type Message = { id: string; role: 'character' | 'user' | 'notice'; text: string; emotion?: Emotion; calm?: boolean; promo?: Promo }
export type TurnInput = { kind: 'choice'; choiceId: string; text: string } | { kind: 'text'; text: string }
export type TurnRequest = { requestId: string; turn: number; input: TurnInput }
// safety: 서버가 위기 입력으로 판단해 장면·턴을 진행하지 않고 안내만 돌려준 응답
// ending: 마지막 턴에서 서버가 정한 엔딩 ID(서버 Mock·API 모드). 브라우저 Mock에는 없다.
export type TurnResponse = { text: string; emotion: Emotion; safety?: true; promo?: Promo; ending?: string | null }
export type ConversationClient = { sendTurn(request: TurnRequest, signal?: AbortSignal): Promise<TurnResponse> }
export type ChatState = {
  messages: Message[]
  completedTurns: number
  emotion: Emotion
  status: 'idle' | 'responding' | 'error' | 'complete'
  pending: TurnRequest | null
  ending: string | null
  resumedFrom?: number // 이어하기로 시작한 턴(0부터). 새 체험이면 없음
}
