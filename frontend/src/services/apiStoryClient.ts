import type { StoryProject, StoryStep } from '../projects/stories/catalog.ts'
import type { StoryClient, StoryTurnRequest } from './storyClient.ts'
import type { StoryReply } from './mockStoryClient.ts'
import { fridgeExpression, fridgeSceneImage } from '../projects/stories/fridgeExpressions.ts'

// 냉장고·구름섬 실제 백엔드(/api/story-chat) 클라이언트.
// - 개인 코드·대화 ID는 이 객체의 메모리에 두고, 이어하기용으로 storyProgress.ts가 이 기기 브라우저에만 저장한다.
//   이어하기는 resume으로 같은 대화를 다시 쓰고 progress()로 서버 진행 장면을 먼저 확인한다. API 키는 서버만 보유한다.
// - requestId는 재시도 동안 유지되며 서버가 같은 requestId의 저장된 응답을 돌려준다(중복 방지).
// - 서버 진행 장면과 응답 장면이 다르면 오류로 처리해 화면 진행과 서버 상태가 어긋나지 않게 한다.

export type StoryApiErrorKind = 'network' | 'timeout' | 'conflict' | 'server' | 'invalid' | 'auth' | 'quota'
export class StoryApiError extends Error {
  readonly kind: StoryApiErrorKind
  readonly status?: number
  readonly retryAfter?: number
  readonly retryable: boolean
  constructor(kind: StoryApiErrorKind, message: string, status?: number, retryAfter?: number, retryable = kind !== 'conflict' && kind !== 'auth') {
    super(message); this.name = 'StoryApiError'; this.kind = kind; this.status = status; this.retryAfter = retryAfter; this.retryable = retryable
  }
}

// Gemini 503(일시 과부하)은 같은 요청 ID로 다시 보낼 수 있지만, 연속 클릭으로 부하를 키우지 않도록 잠시 기다린다.
// 429·504 등 다른 오류의 대기 정책은 바꾸지 않는다.
export const GEMINI_UNAVAILABLE_COOLDOWN_SECONDS = 15

// 화면의 '다시 시도' 노출 여부와 대기 시간. StoryApiError가 아닌 오류(Mock 실패 등)는 기존처럼 즉시 재시도할 수 있다.
export function storyRetryPolicy(error: unknown): { canRetry: boolean; waitSeconds: number } {
  if (!(error instanceof StoryApiError)) return { canRetry: true, waitSeconds: 0 }
  return error.retryable ? { canRetry: true, waitSeconds: error.retryAfter ?? 0 } : { canRetry: false, waitSeconds: 0 }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>
export const SCENARIO_SET = 'scenario_draft_v1'

type Options = { displayName: string; sceneSet?: typeof SCENARIO_SET; provider?: 'gemini' | 'mock'; fetch?: FetchLike; baseUrl?: string; timeoutMs?: number; resume?: { code: string; conversationId: string; project: string; totalTurns: number } }
type Conversation = { code: string; id: string; project: string; totalTurns: number }

const MESSAGES: Record<StoryApiErrorKind, string> = {
  network: '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
  timeout: '응답이 늦어지고 있어요. 다시 시도해 주세요.',
  conflict: '이야기 진행 상태가 서버와 달라요. 새로 시작해 주세요.',
  server: 'AI 응답을 만들지 못했어요. 다시 시도해 주세요.',
  invalid: '응답 형식이 올바르지 않아요. 다시 시도해 주세요.',
  quota: 'Gemini 요청 한도에 도달했어요. 잠시 후 같은 답변을 다시 보낼 수 있어요.',
  auth: '대화 세션을 확인하지 못했어요. 새로 시작해 주세요.',
}

export function storyChoiceId(projectId: string, turn: number, choice: number) {
  return `${projectId}-${String(turn + 1).padStart(2, '0')}-${'abcdefgh'[choice]}`
}

function linkSignals(signal: AbortSignal, timeoutMs: number) {
  const controller = new AbortController()
  let timedOut = false
  const timer = globalThis.setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
  const abort = () => controller.abort()
  if (signal.aborted) controller.abort(); else signal.addEventListener('abort', abort, { once: true })
  return { signal: controller.signal, timedOut: () => timedOut, done: () => { globalThis.clearTimeout(timer); signal.removeEventListener('abort', abort) } }
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null }

export function createApiStoryClient({ displayName, sceneSet, provider = 'gemini', fetch: doFetch = (input, init) => globalThis.fetch(input, init), baseUrl = '', timeoutMs = 180_000, resume }: Options): StoryClient {
  let resolved: Conversation | null = resume ? { code: resume.code, id: resume.conversationId, project: resume.project, totalTurns: resume.totalTurns } : null
  let conversation: Promise<Conversation> | null = resolved ? Promise.resolve(resolved) : null

  async function call(path: string, body: unknown, signal: AbortSignal, code?: string): Promise<unknown> {
    const linked = linkSignals(signal, timeoutMs)
    let response: Response
    try {
      const get = body === undefined
      response = await doFetch(`${baseUrl}${path}`, { method: get ? 'GET' : 'POST', headers: { ...(get ? {} : { 'Content-Type': 'application/json' }), ...(code ? { 'X-Personal-Code': code } : {}), ...(sceneSet ? { 'X-Story-Provider': provider } : {}) }, ...(get ? {} : { body: JSON.stringify(body) }), signal: linked.signal })
    } catch {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      if (linked.timedOut()) throw new StoryApiError('timeout', MESSAGES.timeout)
      throw new StoryApiError('network', MESSAGES.network, undefined)
    } finally { linked.done() }
    if (response.status === 429) {
      const data: unknown = await response.json().catch(() => null)
      const daily = isRecord(data) && isRecord(data.detail) && data.detail.code === 'gemini_quota_daily'
      const delay = response.headers.get('Retry-After')
      const seconds = delay && /^\d+$/.test(delay) ? Number(delay) : undefined
      const message = daily ? 'Gemini 일일 한도에 도달했어요. 한도가 갱신된 후 같은 답변을 다시 보낼 수 있어요.' :
        seconds ? `Gemini 요청 한도에 도달했어요. ${seconds}초 후 다시 시도할 수 있어요.` : MESSAGES.quota
      throw new StoryApiError('quota', message, 429, seconds || undefined)
    }
    if (response.status === 503) {
      const data: unknown = await response.json().catch(() => null)
      if (isRecord(data) && isRecord(data.detail) && data.detail.code === 'gemini_unavailable') {
        throw new StoryApiError('server', `Gemini가 일시적으로 응답할 수 없어요. 잠시 후 같은 답변을 다시 보낼 수 있어요. ${GEMINI_UNAVAILABLE_COOLDOWN_SECONDS}초 뒤 한 번만 눌러 주세요.`, 503, GEMINI_UNAVAILABLE_COOLDOWN_SECONDS)
      }
      // 공급자 불일치·장면 데이터 없음 등 서버 설정 문제는 같은 요청을 반복해도 해결되지 않는다.
      throw new StoryApiError('server', '서버 설정 문제로 이야기를 이어갈 수 없어요. 설정을 확인한 뒤 새로 시작해 주세요.', 503, undefined, false)
    }
    if (response.status === 422) {
      // 장면에 없는 선택지·요청 형식 오류처럼 서버가 요청 자체를 거부한 경우다. 같은 요청을 반복해도 결과가 같다.
      // 정상 응답(200)의 형식 오류는 기존처럼 'invalid'로 다시 시도할 수 있다.
      throw new StoryApiError('invalid', '보낸 답변을 서버가 처리할 수 없어요. 새로 시작해 주세요.', 422, undefined, false)
    }
    if (!response.ok) {
      const kind: StoryApiErrorKind = response.status === 409 ? 'conflict' : response.status === 401 || response.status === 403 || response.status === 404 ? 'auth' : response.status === 422 ? 'invalid' : response.status === 504 ? 'timeout' : 'server'
      throw new StoryApiError(kind, MESSAGES[kind], response.status)
    }
    try { return await response.json() } catch { throw new StoryApiError('invalid', MESSAGES.invalid, response.status) }
  }

  async function start(projectId: string, signal: AbortSignal): Promise<Conversation> {
    const session = await call('/api/sessions', { display_name: displayName.slice(0, 60) || null }, signal)
    const code = isRecord(session) && typeof session.personal_code === 'string' ? session.personal_code : ''
    if (!code) throw new StoryApiError('invalid', MESSAGES.invalid)
    const created = await call('/api/story-chat/conversations', { project: projectId, ...(sceneSet ? { scene_set: sceneSet } : {}) }, signal, code)
    if (!isRecord(created) || typeof created.conversation_id !== 'string' || created.project !== projectId || (sceneSet && created.scene_set !== sceneSet) || typeof created.total_turns !== 'number') throw new StoryApiError('invalid', MESSAGES.invalid)
    return { code, id: created.conversation_id, project: projectId, totalTurns: created.total_turns }
  }

  function ensure(projectId: string, signal: AbortSignal) {
    if (!conversation) {
      // 실패하면 다음 재시도에서 세션/대화를 다시 만든다. 성공한 대화는 이 클라이언트 동안 재사용한다.
      conversation = start(projectId, signal).then(created => { resolved = created; return created }).catch(error => { conversation = null; throw error })
    }
    return conversation
  }

  return {
    session: () => resolved ? { code: resolved.code, conversationId: resolved.id } : null,
    async progress(signal: AbortSignal) {
      if (!resolved) return null
      const data = await call(`/api/story-chat/conversations/${encodeURIComponent(resolved.id)}`, undefined, signal, resolved.code)
      if (!isRecord(data) || data.conversation_id !== resolved.id || data.project !== resolved.project || typeof data.completed_turns !== 'number' || typeof data.total_turns !== 'number') throw new StoryApiError('invalid', MESSAGES.invalid)
      return { completedTurns: data.completed_turns, totalTurns: data.total_turns, finished: data.finished === true }
    },
    async sendTurn(request: StoryTurnRequest, signal: AbortSignal): Promise<StoryReply> {
      const projectId = request.project.id
      const current = await ensure(projectId, signal)
      if (current.project !== projectId || current.totalTurns !== request.project.steps.length) throw new StoryApiError('conflict', MESSAGES.conflict)
      const step = request.project.steps[request.turn]
      const fixed = step.inputMode === 'none'
      const input: { text: string; choice_id?: string } = { text: request.input.text }
      if (request.input.choice !== undefined) {
        const choice = step.choices[request.input.choice]
        input.choice_id = choice?.id ?? storyChoiceId(projectId, request.turn, request.input.choice)
        // 화면에는 호칭을 채운 문구를 보이고, 서버 검증에는 장면 데이터의 원문 문구를 보낸다.
        if (choice?.sourceLabel !== undefined) input.text = choice.sourceLabel
      }
      const path = fixed ? 'fixed-turns' : 'turns'
      const data = await call(`/api/story-chat/conversations/${encodeURIComponent(current.id)}/${path}`, {
        request_id: request.requestId,
        turn: request.turn,
        ...(!fixed ? { input } : {}),
      }, signal, current.code)
      const reply = parseStoryTurnResponse(data, request)
      if (sceneSet && !reply.safety && (reply.meta?.provider !== (fixed ? 'fixed' : provider) || reply.meta.finished !== (request.turn + 1 === current.totalTurns))) {
        throw new StoryApiError('server', 'Gemini 연결 및 서버 진행 상태를 확인해 주세요.')
      }
      return reply
    },
  }
}

export function parseStoryTurnResponse(data: unknown, request: Pick<StoryTurnRequest, 'requestId' | 'turn'>): StoryReply {
  if (!isRecord(data) || !Array.isArray(data.replies)) throw new StoryApiError('invalid', MESSAGES.invalid)
  // 서버 진행 상태와 화면 진행 상태를 맞춘다.
  if (data.safety_notice === true) {
    // 위기 신호 안내: 서버는 장면을 진행하지 않았다(completed_turns가 요청 장면 그대로여야 한다).
    if (data.request_id !== request.requestId || data.turn !== request.turn || data.completed_turns !== request.turn) throw new StoryApiError('conflict', MESSAGES.conflict)
    const [line] = data.replies.filter((item): item is { speaker: string; text: string } => isRecord(item) && typeof item.speaker === 'string' && typeof item.text === 'string')
    return { speaker: line?.speaker ?? '', text: line?.text ?? '', reaction: '', safety: true }
  }
  if (data.request_id !== request.requestId || data.turn !== request.turn || data.completed_turns !== request.turn + 1) throw new StoryApiError('conflict', MESSAGES.conflict)
  const lines = data.replies.filter((line): line is { speaker: string; text: string } => isRecord(line) && typeof line.speaker === 'string' && typeof line.text === 'string' && line.text.trim() !== '')
  if (!lines.length || typeof data.provider !== 'string' || typeof data.model !== 'string') throw new StoryApiError('invalid', MESSAGES.invalid)
  const [first, ...rest] = lines
  return {
    speaker: first.speaker, text: first.text,
    reaction: typeof data.reaction === 'string' && data.reaction ? data.reaction : '이야기가 이어져요',
    followUps: rest.map(line => ({ speaker: line.speaker, text: line.text })),
    meta: {
      provider: data.provider,
      model: data.model,
      latencyMs: typeof data.latency_ms === 'number' ? data.latency_ms : 0,
      replayed: data.replayed === true,
      finished: data.finished === true,
      ...(typeof data.dialogue_provider === 'string' ? { dialogueProvider: data.dialogue_provider } : {}),
      ...(typeof data.fallback_reason === 'string' ? { fallbackReason: data.fallback_reason } : {}),
      ...(typeof data.ending === 'string' && data.ending ? { ending: data.ending } : {}),
    },
  }
}


export async function loadStoryScenario(project: StoryProject, name: string, signal: AbortSignal): Promise<StoryProject> {
  const response = await fetch(`/api/story-chat/scene-sets/${project.id}/${SCENARIO_SET}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]) })
  if (!response.ok) throw new StoryApiError('server', MESSAGES.server, response.status)
  const data: unknown = await response.json()
  const invalid = () => new StoryApiError('invalid', MESSAGES.invalid)
  if (!isRecord(data) || data.project !== project.id || data.scene_set !== SCENARIO_SET ||
      !Array.isArray(data.scenes) || data.scenes.length !== 10 || data.total_turns !== data.scenes.length) throw invalid()

  const address = (text: string) => text.replace(/\[(?:호칭|닉네임)\]/g, () => name)
  const steps = data.scenes.map((scene: unknown, turn): StoryStep => {
    if (!isRecord(scene) || scene.turn !== turn || typeof scene.title !== 'string' ||
        typeof scene.situation !== 'string' || (scene.input_mode !== 'input' && scene.input_mode !== 'none') ||
        !Array.isArray(scene.opening_lines) || !Array.isArray(scene.system_messages) || !Array.isArray(scene.choices)) throw invalid()
    const openingLines = scene.opening_lines.map((line: unknown) => {
      if (!isRecord(line) || typeof line.speaker !== 'string' || typeof line.text !== 'string') throw invalid()
      const direction = typeof line.direction === 'string' && line.direction
        ? project.id === 'fridge' ? `[디스플레이: ${line.direction}]\n` : `(${line.direction}) `
        : ''
      return { speaker: line.speaker, text: address(direction + line.text) }
    })
    return {
      title: scene.title,
      situation: address(scene.situation),
      speaker: openingLines[0]?.speaker ?? project.characters[0].name,
      ...(project.id === 'fridge' ? { sceneImage: fridgeSceneImage(turn), expression: fridgeExpression(turn) } : {}),
      text: '',
      reply: '',
      inputMode: scene.input_mode,
      openingLines,
      systemMessages: scene.system_messages.map((message: unknown) => {
        if (typeof message !== 'string') throw invalid()
        return address(message)
      }),
      choices: scene.choices.map((choice: unknown) => {
        if (!isRecord(choice) || typeof choice.choice_id !== 'string' || typeof choice.label !== 'string') throw invalid()
        return { id: choice.choice_id, label: address(choice.label), sourceLabel: choice.label, reply: '', reaction: '' }
      }),
    }
  })
  return { ...project, steps }
}
