import type { ConversationClient, TurnRequest, TurnResponse } from '../features/chat/types.ts'
import { userNoteStore } from './userNoteStore.ts'
import type { UserNoteStore } from './userNoteStore.ts'
import { createTrace, recordSource } from './devSource.ts'
import type { SourceTrace } from './devSource.ts'

// 푸르마 실제 백엔드(/api/chat) 클라이언트. VITE_PURUMA_CLIENT=api일 때만 chatClient.ts가 선택한다.
// - 개인 코드·대화 ID는 이 객체의 메모리에만 둔다(localStorage·로그에 저장하지 않음). API 키는 서버만 보유한다.
// - 매 요청에 로컬 기억을 notes로 보내고(비어 있으면 []), 응답의 notes로 저장소를 덮어쓴다.
// - 감정은 /api/chat 응답에 없다. 기본값 'happy'를 쓰며 응답을 분석한 값이 아니다(감정 표현은 후속 작업).
// - 오류가 나도 Mock 응답으로 대체하지 않는다.
// - /api/chat에는 요청 ID 중복 방지가 없다. 이 클라이언트는 성공한 requestId의 응답을 기억해 같은 요청의
//   재시도가 서버 메시지·기억을 다시 갱신하지 않게 한다. 응답을 못 받은 네트워크 오류·시간 초과는 서버가
//   처리했는지 알 수 없으므로 재시도하면 서버에 같은 메시지가 한 번 더 저장될 수 있다(알려진 한계).

export function purumaClientMode(env: Record<string, string | undefined> | undefined = (import.meta as { env?: Record<string, string | undefined> }).env): 'mock' | 'api' {
  return env?.VITE_PURUMA_CLIENT === 'api' ? 'api' : 'mock'
}

export type ApiChatErrorKind = 'network' | 'timeout' | 'auth' | 'conflict' | 'invalid' | 'quota' | 'server'
export class ApiChatError extends Error {
  readonly kind: ApiChatErrorKind
  readonly status?: number
  constructor(kind: ApiChatErrorKind, message: string, status?: number) {
    super(message); this.name = 'ApiChatError'; this.kind = kind; this.status = status
  }
}

const MESSAGES: Record<ApiChatErrorKind, string> = {
  network: '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
  timeout: '응답이 늦어지고 있어요. 다시 시도해 주세요.',
  auth: '대화 세션을 확인하지 못했어요. 처음부터 다시 시작해 주세요.',
  conflict: '이미 끝난 대화예요. 처음부터 다시 시작해 주세요.',
  invalid: '요청 형식이 올바르지 않아요. 입력을 확인하고 다시 시도해 주세요.',
  quota: '요청이 너무 많아요. 잠시 후 같은 답변을 다시 보낼 수 있어요.',
  server: 'AI 응답을 만들지 못했어요. 진행은 그대로예요. 다시 시도해 주세요.',
}

export function errorKindForStatus(status: number): ApiChatErrorKind {
  if (status === 401 || status === 403 || status === 404) return 'auth'
  if (status === 409) return 'conflict'
  if (status === 422 || status === 400) return 'invalid'
  if (status === 429) return 'quota'
  return 'server' // 502 등
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>
type Options = {
  displayName: string
  fetch?: FetchLike
  baseUrl?: string
  timeoutMs?: number
  store?: UserNoteStore
}
export type ApiChatClient = ConversationClient & { lastErrorMessage(): string; reset(): void; trace: SourceTrace }

const DEFAULT_EMOTION: TurnResponse['emotion'] = 'happy'

export function createApiChatClient({
  displayName, fetch: doFetch = (input, init) => globalThis.fetch(input, init), baseUrl = '', timeoutMs = 60_000, store = userNoteStore,
}: Options): ApiChatClient {
  let session: { code: string; conversationId: string } | null = null
  let lastError: ApiChatError | null = null
  const trace = createTrace('puruma', 'api')
  const done = new Map<string, TurnResponse>()
  const inFlight = new Map<string, Promise<TurnResponse>>()

  async function call(path: string, body: unknown, signal: AbortSignal | undefined, code?: string): Promise<unknown> {
    const timeout = AbortSignal.timeout(timeoutMs)
    let response: Response
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(code ? { 'X-Personal-Code': code } : {}) },
        body: JSON.stringify(body),
        signal: AbortSignal.any([...(signal ? [signal] : []), timeout]),
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw timeout.aborted ? new ApiChatError('timeout', MESSAGES.timeout) : new ApiChatError('network', MESSAGES.network)
    }
    if (!response.ok) { const kind = errorKindForStatus(response.status); throw new ApiChatError(kind, MESSAGES[kind], response.status) }
    try { return await response.json() } catch { throw new ApiChatError('server', MESSAGES.server, response.status) }
  }

  async function ensureSession(signal?: AbortSignal) {
    if (session) return session
    const data = await call('/api/sessions', { display_name: displayName.slice(0, 60) || null, persona_slug: 'puruma' }, signal) as
      { personal_code?: unknown; conversation?: { id?: unknown } | null }
    const conversationId = data.conversation?.id
    if (typeof data.personal_code !== 'string' || typeof conversationId !== 'string') throw new ApiChatError('server', MESSAGES.server)
    session = { code: data.personal_code, conversationId }
    return session
  }

  async function run(request: TurnRequest, signal?: AbortSignal): Promise<TurnResponse> {
    const epoch = store.getEpoch()
    const current = await ensureSession(signal)
    const data = await call('/api/chat', {
      conversation_id: current.conversationId, message: request.input.text, notes: store.read(),
    }, signal, current.code) as { reply?: unknown; notes?: unknown; provider?: unknown; safety_notice?: unknown }
    if (data.safety_notice === true) {
      // 위기 안내 응답: 서버는 입력·기억·상태를 바꾸지 않았다. 기억(notes)을 쓰지 않고 안내로만 처리한다.
      if (typeof data.reply !== 'string' || !data.reply.trim()) throw new ApiChatError('server', MESSAGES.server)
      return { text: data.reply.trim(), emotion: DEFAULT_EMOTION, safety: true }
    }
    if (typeof data.reply !== 'string' || !data.reply.trim() || !Array.isArray(data.notes)) throw new ApiChatError('server', MESSAGES.server)
    recordSource(trace, { provider: typeof data.provider === 'string' ? data.provider : undefined })
    if (store.getEpoch() === epoch) store.write(data.notes) // 요청 중 사용자가 기억을 지웠다면 되살리지 않는다.
    return { text: data.reply.trim(), emotion: DEFAULT_EMOTION }
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
            recordSource(trace, { error: lastError.kind + (lastError.status ? ` ${lastError.status}` : '') }) // API 실패를 Mock으로 대체하지 않고 그대로 기록
          }
          throw error
        },
      ).finally(() => { inFlight.delete(request.requestId) })
      inFlight.set(request.requestId, promise)
      return promise
    },
    trace,
    lastErrorMessage: () => lastError?.message ?? MESSAGES.server,
    reset() { session = null; lastError = null; done.clear(); inFlight.clear() }, // 다시 체험하기: 새 서버 대화. 기억은 유지
  }
}
