export type Emotion = 'confused' | 'happy' | 'sparkle'
export type Choice = { id: string; label: string }
// role 'notice'는 위기 안내 시스템 말풍선. calm은 장난스러운 리액션 문구·기호를 붙이지 않는 캐릭터 대사.
export type Message = { id: string; role: 'character' | 'user' | 'notice'; text: string; emotion?: Emotion; calm?: boolean }
export type TurnInput = { kind: 'choice'; choiceId: string; text: string } | { kind: 'text'; text: string }
export type TurnRequest = { requestId: string; turn: number; input: TurnInput }
export type TurnResponse = { text: string; emotion: Emotion }
export type ConversationClient = { sendTurn(request: TurnRequest, signal?: AbortSignal): Promise<TurnResponse> }
export type ChatState = {
  messages: Message[]
  completedTurns: number
  emotion: Emotion
  status: 'idle' | 'responding' | 'error' | 'complete'
  pending: TurnRequest | null
}
