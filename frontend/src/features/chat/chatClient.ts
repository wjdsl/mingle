import type { ConversationClient } from './types.ts'
import { mockConversationClient } from '../../services/mockConversationClient.ts'
import { createPurumaStoryClient, purumaStoryMode } from '../../services/apiPurumaStoryClient.ts'
import type { PurumaMode } from '../../services/apiPurumaStoryClient.ts'
import { createTrace, recordSource } from '../../services/devSource.ts'
import type { SourceTrace } from '../../services/devSource.ts'

// 푸르마 대화 클라이언트 선택. 기본은 브라우저 Mock이다.
// VITE_PURUMA_CLIENT=scenario-mock이면 서버 Mock, =api이면 서버의 실제 AI로 /api/story-chat 10턴을 진행한다.
// (예전 /api/chat 클라이언트 apiChatClient.ts는 지우지 않았지만 푸르마 화면에서는 더 이상 쓰지 않는다.)
export type PurumaClient = ConversationClient & {
  mode: PurumaMode; lastErrorMessage(): string; reset(): void; trace: SourceTrace
  // 서버 모드만: 이어하기용 서버 대화 정보와 서버 진행 턴. 브라우저 Mock에는 없다.
  session?(): { code: string; conversationId: string } | null
  progress?(signal?: AbortSignal): Promise<{ completedTurns: number; totalTurns: number; finished: boolean } | null>
}

export function createPurumaClient(displayName: string, mode = purumaStoryMode(), resume?: { code: string; conversationId: string }): PurumaClient {
  if (mode !== 'mock') return { ...createPurumaStoryClient({ displayName, provider: mode === 'api' ? 'gemini' : 'mock', resume }), mode }
  const trace = createTrace('puruma', 'mock')
  return {
    async sendTurn(request, signal) { const response = await mockConversationClient.sendTurn(request, signal); recordSource(trace, { provider: 'mock' }); return response },
    mode: 'mock', trace, lastErrorMessage: () => 'Mock 응답을 불러오지 못했어요. 진행은 그대로예요.', reset() {},
  }
}
