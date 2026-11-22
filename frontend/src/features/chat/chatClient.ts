import type { ConversationClient } from './types.ts'
import { mockConversationClient } from '../../services/mockConversationClient.ts'
import { createApiChatClient, purumaClientMode } from '../../services/apiChatClient.ts'
import { createTrace, recordSource } from '../../services/devSource.ts'
import type { SourceTrace } from '../../services/devSource.ts'

// 푸르마 대화 클라이언트 선택. 기본은 Mock이며 빌드 환경변수 VITE_PURUMA_CLIENT=api일 때만 실제 API를 쓴다.
export type PurumaClient = ConversationClient & { mode: 'mock' | 'api'; lastErrorMessage(): string; reset(): void; trace: SourceTrace }

export function createPurumaClient(displayName: string, mode = purumaClientMode()): PurumaClient {
  if (mode === 'api') return { ...createApiChatClient({ displayName }), mode: 'api' }
  const trace = createTrace('puruma', 'mock')
  return {
    async sendTurn(request, signal) { const response = await mockConversationClient.sendTurn(request, signal); recordSource(trace, { provider: 'mock' }); return response },
    mode: 'mock', trace, lastErrorMessage: () => 'Mock 응답을 불러오지 못했어요. 진행은 그대로예요.', reset() {},
  }
}
