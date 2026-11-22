import { SCENES, TOTAL_TURNS, openingText } from '../../projects/puruma/scenes.ts'
import { crisisCareLine } from '../../services/crisisSafety.ts'
import type { ChatState, Message, TurnRequest, TurnResponse } from './types'

// 푸르마 10턴. 응답을 받으면 다음 장면의 첫 대사(구간 전환·SOS)를 이어 붙인다.
function openingMessage(turn: number): Message {
  return { id: `opening-${turn}`, role: 'character', text: openingText(turn), emotion: SCENES[turn].openingEmotion }
}

export const initialState = (): ChatState => ({
  messages: [{ ...openingMessage(0), id: 'opening' }],
  completedTurns: 0, emotion: SCENES[0].openingEmotion, status: 'idle', pending: null, ending: null,
})
type Action = { type: 'send'; request: TurnRequest } | { type: 'retry' } |
  { type: 'success'; requestId: string; response: TurnResponse } |
  { type: 'failure'; requestId: string } | { type: 'reset' } |
  { type: 'crisis'; id: string; text: string } | { type: 'restore'; turn: number }

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
    case 'success': {
      if (state.status !== 'responding' || state.pending?.requestId !== action.requestId) return state
      if (action.response.safety) {
        // 서버가 위기 입력으로 판단: 턴·감정·진행 상태는 그대로 두고 안내와 차분한 반응만 붙인다.
        return { ...state, pending: null, status: 'idle', messages: [...state.messages,
          { id: `${action.requestId}-notice`, role: 'notice', text: '' },
          { id: `${action.requestId}-care`, role: 'character', text: action.response.text, emotion: 'confused', calm: true }] }
      }
      const completed = state.completedTurns + 1
      const done = completed >= TOTAL_TURNS
      const reply: Message = { id: `${action.requestId}-reply`, role: 'character', text: action.response.text, emotion: action.response.emotion,
        ...(action.response.promo ? { promo: action.response.promo } : {}) }
      return { ...state, completedTurns: completed, pending: null,
        status: done ? 'complete' : 'idle', emotion: action.response.emotion,
        ending: done ? action.response.ending ?? null : state.ending,
        messages: [...state.messages, reply, ...(done ? [] : [openingMessage(completed)])] }
    }
    case 'reset': return initialState()
    case 'restore': {
      // 이어하기: 아직 아무것도 보내지 않은 새 대화에서만, 저장된 턴의 첫 대사부터 다시 보여 준다(이전 대화 원문은 저장하지 않는다).
      if (state.status !== 'idle' || state.completedTurns !== 0 || state.messages.length !== 1) return state
      if (!Number.isInteger(action.turn) || action.turn < 1 || action.turn >= TOTAL_TURNS) return state
      return { ...state, completedTurns: action.turn, emotion: SCENES[action.turn].openingEmotion, resumedFrom: action.turn, messages: [openingMessage(action.turn)] }
    }
    case 'crisis':
      // 위기 신호: 턴·상태를 바꾸지 않고 안내와 캐릭터의 짧은 반응만 붙인다(서버 호출 없음).
      if (state.status !== 'idle' || validateInput(action.text)) return state
      return { ...state, messages: [...state.messages,
        { id: action.id, role: 'user', text: action.text.trim() },
        { id: `${action.id}-notice`, role: 'notice', text: '' },
        { id: `${action.id}-care`, role: 'character', text: crisisCareLine('puruma').text, emotion: 'confused', calm: true }] }
  }
}
