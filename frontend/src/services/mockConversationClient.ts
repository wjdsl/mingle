import type { ConversationClient, TurnRequest, TurnResponse } from '../features/chat/types'
import { SCENES, TOTAL_TURNS } from '../projects/puruma/scenes.ts'

// 푸르마 브라우저 Mock: 장면의 고정 반응만 돌려준다. 스탯·홍보·엔딩 판정은 하지 않는다(서버 Mock·API 모드에서만).
export function resolveMock(request: TurnRequest): TurnResponse {
  if (request.turn < 1 || request.turn > TOTAL_TURNS) throw new Error('체험 범위를 벗어난 턴입니다.')
  const scene = SCENES[request.turn - 1]
  if (request.input.kind === 'choice') {
    const choiceId = request.input.choiceId
    const choice = scene.choices.find(item => item.id === choiceId)
    if (!choice) throw new Error('현재 턴의 선택지가 아닙니다.')
    return { text: choice.reply, emotion: choice.emotion }
  }
  return { text: scene.freeReply, emotion: scene.freeEmotion }
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
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mockError') === 'once' && !failedRequests.has(request.requestId)) {
      failedRequests.add(request.requestId)
      throw new Error('검증용 Mock 오류')
    }
    return resolveMock(request)
  },
}
const failedRequests = new Set<string>()
