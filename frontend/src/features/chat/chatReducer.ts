import { opening } from '../../projects/puruma/mockConversation.ts'
import type { ChatState, TurnRequest, TurnResponse } from './types'

export const initialState = (): ChatState => ({
  messages: [{ id: 'opening', role: 'character', text: opening, emotion: 'confused' }],
  completedTurns: 0, emotion: 'confused', status: 'idle', pending: null,
})
type Action = { type: 'send'; request: TurnRequest } | { type: 'retry' } |
  { type: 'success'; requestId: string; response: TurnResponse } |
  { type: 'failure'; requestId: string } | { type: 'reset' }

export function validateInput(text: string): string | null {
  if (!text.trim()) return '한 글자라도 적어 주세요.'
  if (Array.from(text).length > 300) return '메시지는 300자 이내로 적어 주세요.'
  return null
}
export function chatReducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'send':
      if (state.status !== 'idle' || action.request.turn !== state.completedTurns + 1 || validateInput(action.request.input.text)) return state
      return { ...state, status: 'responding', pending: action.request,
        messages: [...state.messages, { id: action.request.requestId, role: 'user', text: action.request.input.text }] }
    case 'retry': return state.status === 'error' ? { ...state, status: 'responding' } : state
    case 'failure': return state.pending?.requestId === action.requestId && state.status === 'responding' ? { ...state, status: 'error' } : state
    case 'success':
      if (state.status !== 'responding' || state.pending?.requestId !== action.requestId) return state
      return { ...state, completedTurns: state.completedTurns + 1, pending: null,
        status: state.completedTurns + 1 === 2 ? 'complete' : 'idle', emotion: action.response.emotion,
        messages: [...state.messages, { id: `${action.requestId}-reply`, role: 'character', text: action.response.text, emotion: action.response.emotion }] }
    case 'reset': return initialState()
  }
}
