import type { ConversationClient, TurnResponse } from '../features/chat/types.ts'

export function parseTurnResponse(value: unknown): TurnResponse {
  if (!value || typeof value !== 'object') throw new Error('잘못된 AI 응답')
  const data = value as Record<string, unknown>
  if (Object.keys(data).length !== 2 || typeof data.text !== 'string' || !data.text.trim() || Array.from(data.text).length > 2000 ||
      !['confused', 'happy', 'sparkle'].includes(String(data.emotion))) throw new Error('잘못된 AI 응답')
  return { text: data.text.trim(), emotion: data.emotion as TurnResponse['emotion'] }
}

export const geminiConversationClient: ConversationClient = {
  async sendTurn(request, signal) {
    const response = await fetch('/api/chat/turn', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(135000)]),
    })
    if (!response.ok) throw new Error('AI 응답 요청 실패')
    return parseTurnResponse(await response.json())
  },
}
