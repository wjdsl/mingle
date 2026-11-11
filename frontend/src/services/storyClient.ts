import type { StoryProject } from '../projects/stories/catalog'
import { requestStoryReply } from './mockStoryClient.ts'
import type { StoryReply } from './mockStoryClient.ts'

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
// 실제 API는 StoryClient를 구현해 주입한다. URL/인증/턴 전환 계약은 연동 시 명시한다.
