import type { StoryProject } from '../projects/stories/catalog'
import { requestStoryReply } from './mockStoryClient.ts'
import type { StoryReply } from './mockStoryClient.ts'
import { createApiStoryClient, SCENARIO_SET } from './apiStoryClient.ts'
import { createTrace, recordSource } from './devSource.ts'
import type { SourceTrace } from './devSource.ts'

// UI 경계 계약이며 백엔드 HTTP 스키마와 구분한다.
export type StoryTurnRequest = {
 requestId: string
 project: StoryProject
 turn: number
 input: { text: string; choice?: number }
 mockFailure?: boolean
}
export interface StoryClient { sendTurn(request: StoryTurnRequest, signal: AbortSignal): Promise<StoryReply> }
export const mockStoryClient: StoryClient = {
 sendTurn: (request, signal) => requestStoryReply(request.project, request.turn, request.input.choice, signal, request.mockFailure),
}
// 실제 API 클라이언트는 apiStoryClient.ts(/api/story-chat). 빌드 환경변수 VITE_STORY_CLIENT=api 일 때만 사용한다.
// 기본값은 Mock이며, API 모드에서 실패해도 Mock으로 몰래 대체하지 않는다.
export function storyClientMode(): 'api' | 'scenario-mock' | 'mock' {
 const mode = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_STORY_CLIENT
 return mode === 'api' || mode === 'scenario-mock' ? mode : 'mock'
}
// 개발용 출처 추적 래퍼. 응답·오류를 그대로 전달하며 실패를 성공으로 바꾸지 않는다.
export type TracedStoryClient = StoryClient & { trace: SourceTrace }
export function withSourceTrace(client: StoryClient, mode: string): TracedStoryClient {
  const trace = createTrace('story', mode)
  return {
    trace,
    async sendTurn(request, signal) {
      try {
        const reply = await client.sendTurn(request, signal)
        recordSource(trace, {
          provider: reply.meta?.provider ?? 'mock',
          model: reply.meta?.model,
          dialogueProvider: reply.meta?.dialogueProvider,
          fallbackReason: reply.meta?.fallbackReason,
        })
        return reply
      } catch (error) {
        if (!signal.aborted) recordSource(trace, { error: error instanceof Error ? error.name : 'error' })
        throw error
      }
    },
  }
}
export function createSessionStoryClient(displayName: string): TracedStoryClient {
  const mode = storyClientMode()
  return withSourceTrace(mode === 'mock' ? mockStoryClient : createApiStoryClient({
    displayName,
    sceneSet: SCENARIO_SET,
    provider: mode === 'api' ? 'gemini' : 'mock',
  }), mode)
}
