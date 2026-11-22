import type { ConversationClient, Emotion, Promo, TurnRequest, TurnResponse } from '../features/chat/types.ts'
import { ApiChatError, errorKindForStatus } from './apiChatClient.ts'
import { userNoteStore } from './userNoteStore.ts'
import type { UserNoteStore } from './userNoteStore.ts'
import { createTrace, recordSource } from './devSource.ts'
import type { SourceTrace } from './devSource.ts'

// 푸르마 10턴 서버 클라이언트(/api/story-chat, project=puruma, scene_set=puruma_draft_v1).
// - VITE_PURUMA_CLIENT=api: 서버의 실제 AI(Gemini). =scenario-mock: 서버 Mock(백엔드 LLM_PROVIDER=mock)으로 같은 10턴·판정을 비용 없이 확인.
// - 상태(스탯·친밀도)·홍보·엔딩은 서버가 턴 기록으로 계산한다. 브라우저에는 로컬 기억(notes)만 저장한다(userNoteStore).
// - 개인 코드·대화 ID는 이 객체가 갖고, 이어하기용으로 storyProgress.ts가 이 기기 브라우저에만 저장한다(대화 원문 제외).
//   이어하기는 resume으로 같은 서버 대화를 다시 쓰고 progress()로 서버 진행 턴을 먼저 확인한다.
// - request_id는 재시도 동안 유지되고 서버가 같은 요청의 저장된 응답을 돌려준다(중복 적용 없음).
// - AI가 실패하면 서버가 장면의 고정 대사로 진행한다(provider=fallback). 화면에는 따로 표시하지 않는다.

export type PurumaMode = 'mock' | 'scenario-mock' | 'api'
export function purumaStoryMode(env: Record<string, string | undefined> | undefined = (import.meta as { env?: Record<string, string | undefined> }).env): PurumaMode {
  const value = env?.VITE_PURUMA_CLIENT
  return value === 'api' || value === 'scenario-mock' ? value : 'mock'
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>
type Options = { displayName: string; provider: 'gemini' | 'mock'; fetch?: FetchLike; baseUrl?: string; timeoutMs?: number; store?: UserNoteStore; resume?: { code: string; conversationId: string } }
export type ServerProgress = { completedTurns: number; totalTurns: number; finished: boolean }
export type PurumaStoryClient = ConversationClient & {
  lastErrorMessage(): string; reset(): void; trace: SourceTrace
  session(): { code: string; conversationId: string } | null
  progress(signal?: AbortSignal): Promise<ServerProgress | null>
}

const MESSAGES = {
  network: '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
  timeout: '응답이 늦어지고 있어요. 다시 시도해 주세요.',
  auth: '대화 세션을 확인하지 못했어요. 처음부터 다시 시작해 주세요.',
  conflict: '이야기 진행 상태가 서버와 달라요. 처음부터 다시 시작해 주세요.',
  invalid: '보낸 답변을 서버가 처리할 수 없어요. 처음부터 다시 시작해 주세요.',
  quota: '요청이 너무 많아요. 잠시 후 같은 답변을 다시 보낼 수 있어요.',
  server: 'AI 응답을 만들지 못했어요. 진행은 그대로예요. 다시 시도해 주세요.',
} as const
const EMOTIONS: Emotion[] = ['confused', 'happy', 'sparkle']

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null }

export function parsePromo(value: unknown): Promo | undefined {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.url !== 'string' || !/^https:\/\//.test(value.url)) return undefined
  return { id: value.id, url: value.url, label: typeof value.label === 'string' ? value.label : '', sourceName: typeof value.source_name === 'string' ? value.source_name : '' }
}

export function createPurumaStoryClient({
  displayName, provider, fetch: doFetch = (input, init) => globalThis.fetch(input, init), baseUrl = '', timeoutMs = 180_000, store = userNoteStore, resume,
}: Options): PurumaStoryClient {
  let resolved: { code: string; id: string } | null = resume ? { code: resume.code, id: resume.conversationId } : null
  let session: Promise<{ code: string; id: string }> | null = resolved ? Promise.resolve(resolved) : null
  let lastError: ApiChatError | null = null
  const trace = createTrace('puruma', provider === 'gemini' ? 'api' : 'scenario-mock')
  const done = new Map<string, TurnResponse>()
  const inFlight = new Map<string, Promise<TurnResponse>>()

  async function call(path: string, body: unknown, signal: AbortSignal | undefined, code?: string): Promise<unknown> {
    const timeout = AbortSignal.timeout(timeoutMs)
    const get = body === undefined
    let response: Response
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        method: get ? 'GET' : 'POST',
        headers: { ...(get ? {} : { 'Content-Type': 'application/json' }), 'X-Story-Provider': provider, ...(code ? { 'X-Personal-Code': code } : {}) },
        ...(get ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.any([...(signal ? [signal] : []), timeout]),
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw timeout.aborted ? new ApiChatError('timeout', MESSAGES.timeout) : new ApiChatError('network', MESSAGES.network)
    }
    if (!response.ok) { const kind = errorKindForStatus(response.status); throw new ApiChatError(kind, MESSAGES[kind], response.status) }
    try { return await response.json() } catch { throw new ApiChatError('server', MESSAGES.server, response.status) }
  }

  function ensure(signal?: AbortSignal) {
    if (!session) {
      session = (async () => {
        const created = await call('/api/sessions', { display_name: displayName.slice(0, 60) || null }, signal)
        const code = isRecord(created) && typeof created.personal_code === 'string' ? created.personal_code : ''
        if (!code) throw new ApiChatError('server', MESSAGES.server)
        const conversation = await call('/api/story-chat/conversations', { project: 'puruma' }, signal, code)
        if (!isRecord(conversation) || typeof conversation.conversation_id !== 'string' || conversation.project !== 'puruma') throw new ApiChatError('server', MESSAGES.server)
        resolved = { code, id: conversation.conversation_id }
        return resolved
      })().catch(error => { session = null; throw error })
    }
    return session
  }

  async function run(request: TurnRequest, signal?: AbortSignal): Promise<TurnResponse> {
    const epoch = store.getEpoch()
    const current = await ensure(signal)
    const data = await call(`/api/story-chat/conversations/${encodeURIComponent(current.id)}/turns`, {
      request_id: request.requestId,
      turn: request.turn - 1,
      input: { text: request.input.text, ...(request.input.kind === 'choice' ? { choice_id: request.input.choiceId } : {}) },
      notes: store.read(),
    }, signal, current.code)
    if (!isRecord(data) || !Array.isArray(data.replies)) throw new ApiChatError('server', MESSAGES.server)
    const text = data.replies.map(line => isRecord(line) && typeof line.text === 'string' ? line.text.trim() : '').filter(Boolean).join('\n')
    if (data.safety_notice === true) {
      // 위기 안내: 서버는 진행·기억을 바꾸지 않았다. 받은 기억을 덮어쓰지 않는다.
      if (!text) throw new ApiChatError('server', MESSAGES.server)
      return { text, emotion: 'confused', safety: true }
    }
    if (!text || data.turn !== request.turn - 1) throw new ApiChatError('server', MESSAGES.server)
    recordSource(trace, { provider: typeof data.provider === 'string' ? data.provider : undefined, model: typeof data.model === 'string' ? data.model : undefined })
    if (Array.isArray(data.notes) && store.getEpoch() === epoch) store.write(data.notes) // 요청 중 사용자가 기억을 지웠다면 되살리지 않는다.
    const emotion = EMOTIONS.includes(data.emotion as Emotion) ? data.emotion as Emotion : 'happy'
    const promo = parsePromo(data.promo)
    return { text, emotion, ...(promo ? { promo } : {}), ending: data.finished === true && typeof data.ending === 'string' ? data.ending : null }
  }

  return {
    async sendTurn(request, signal) {
      const cached = done.get(request.requestId)
      if (cached) return cached
      const running = inFlight.get(request.requestId)
      if (running) return running
      lastError = null
      const promise = run(request, signal).then(
        response => { done.set(request.requestId, response); return response },
        error => {
          if (!signal?.aborted) {
            lastError = error instanceof ApiChatError ? error : new ApiChatError('server', MESSAGES.server)
            recordSource(trace, { error: lastError.kind + (lastError.status ? ` ${lastError.status}` : '') })
          }
          throw error
        },
      ).finally(() => { inFlight.delete(request.requestId) })
      inFlight.set(request.requestId, promise)
      return promise
    },
    trace,
    session: () => resolved ? { code: resolved.code, conversationId: resolved.id } : null,
    async progress(signal) {
      if (!resolved) return null
      const data = await call(`/api/story-chat/conversations/${encodeURIComponent(resolved.id)}`, undefined, signal, resolved.code)
      if (!isRecord(data) || data.conversation_id !== resolved.id || data.project !== 'puruma' || typeof data.completed_turns !== 'number' || typeof data.total_turns !== 'number') throw new ApiChatError('server', MESSAGES.server)
      return { completedTurns: data.completed_turns, totalTurns: data.total_turns, finished: data.finished === true }
    },
    lastErrorMessage: () => lastError?.message ?? MESSAGES.server,
    reset() { session = null; resolved = null; lastError = null; done.clear(); inFlight.clear() }, // 다시 체험하기: 새 서버 대화. 기억은 유지
  }
}
