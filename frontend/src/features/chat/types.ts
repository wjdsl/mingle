export type Emotion = 'confused' | 'happy' | 'sparkle'
export type Choice = { id: string; label: string }
export type Message = { id: string; role: 'character' | 'user'; text: string; emotion?: Emotion }
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
