import type { ConversationClient, TurnRequest, TurnResponse } from '../features/chat/types'
import { choices, firstResponses, secondResponses } from '../projects/puruma/mockConversation'

export function resolveMock(request: TurnRequest): TurnResponse {
  if (request.turn < 1 || request.turn > 2) throw new Error('시연 범위를 벗어난 턴입니다.')
  if (request.input.kind === 'choice') {
    if (!choices[request.turn - 1].some(choice => choice.id === (request.input.kind === 'choice' ? request.input.choiceId : ''))) {
      throw new Error('현재 턴의 선택지가 아닙니다.')
    }
    return (request.turn === 1 ? firstResponses : secondResponses)[request.input.choiceId]
  }
  return request.turn === 1
    ? { text: '선배, 이야기해 줘서 고마워요! 우선 강의실부터 같이 찾아가요.\n앗, 도착했는데 벌써 수업 중이에요… 조용히 들어가 볼까요?', emotion: 'happy' }
    : { text: '선배 말을 들으니 조금 안심돼요. 살금살금… 또각!\n말발굽 소리는 났지만 무사히 자리에 앉았어요. 함께해 줘서 고마워요, 히히힝!', emotion: 'sparkle' }
}

export const mockConversationClient: ConversationClient = {
  async sendTurn(request, signal) {
    await new Promise<void>((resolve, reject) => {
      if (signal?.aborted) { reject(new DOMException('중단됨', 'AbortError')); return }
      const onAbort = () => { clearTimeout(timer); reject(new DOMException('중단됨', 'AbortError')) }
      const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve() }, 700)
      signal?.addEventListener('abort', onAbort, { once: true })
    })
    // ?mockError=once는 로컬 시연에서 첫 요청 실패/재시도 검증용이다.
    if (new URLSearchParams(window.location.search).get('mockError') === 'once' && !failedRequests.has(request.requestId)) {
      failedRequests.add(request.requestId)
      throw new Error('검증용 Mock 오류')
    }
    return resolveMock(request)
  },
}
const failedRequests = new Set<string>()
