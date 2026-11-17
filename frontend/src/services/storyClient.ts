import type { StoryProject } from '../projects/stories/catalog'
import { requestStoryReply } from './mockStoryClient.ts'
import type { StoryReply } from './mockStoryClient.ts'
import { createApiStoryClient } from './apiStoryClient.ts'

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
export function storyClientMode(): 'api' | 'mock' {
 return (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_STORY_CLIENT === 'api' ? 'api' : 'mock'
}
export function createSessionStoryClient(displayName: string): StoryClient {
 return storyClientMode() === 'api' ? createApiStoryClient({ displayName }) : mockStoryClient
}
