import type { StoryProject } from '../projects/stories/catalog'
import { requestStoryReply } from './mockStoryClient.ts'
import type { StoryReply } from './mockStoryClient.ts'
import { createApiStoryClient, SCENARIO_SET } from './apiStoryClient.ts'

// UI 경계 계약이며 백엔드 HTTP 스키마와 구분한다.
export type StoryTurnRequest = {
 requestId: string
 project: StoryProject
 turn: number
 input: { text: string; choice?: number }
 mockFailure?: boolean
}
export interface StoryClient {
 sendTurn(request: StoryTurnRequest, signal: AbortSignal): Promise<StoryReply>
 // API 모드만: 이어하기용 서버 대화 정보와 서버 진행 장면. Mock에는 없다.
 session?(): { code: string; conversationId: string } | null
 progress?(signal: AbortSignal): Promise<{ completedTurns: number; totalTurns: number; finished: boolean } | null>
}
export const mockStoryClient: StoryClient = {
 sendTurn: (request, signal) => requestStoryReply(request.project, request.turn, request.input.choice, signal, request.mockFailure),
}
// 실제 API 클라이언트는 apiStoryClient.ts(/api/story-chat). 빌드 환경변수 VITE_STORY_CLIENT=api 일 때만 사용한다.
// 기본값은 Mock이며, API 모드에서 실패해도 Mock으로 몰래 대체하지 않는다.
export function storyClientMode(): 'api' | 'scenario-mock' | 'mock' {
 const mode = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_STORY_CLIENT
 return mode === 'api' || mode === 'scenario-mock' ? mode : 'mock'
}
export function createSessionStoryClient(displayName: string, resume?: { code: string; conversationId: string; project: string; totalTurns: number }): StoryClient {
 const mode = storyClientMode()
 return mode === 'mock' ? mockStoryClient : createApiStoryClient({
   displayName,
   sceneSet: SCENARIO_SET,
   provider: mode === 'api' ? 'gemini' : 'mock',
   resume,
 })
}
