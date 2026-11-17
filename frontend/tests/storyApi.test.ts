import { test } from 'node:test'
import assert from 'node:assert/strict'
import { projects } from '../src/projects/stories/catalog.ts'
import { StoryApiError, createApiStoryClient, parseStoryTurnResponse, storyChoiceId } from '../src/services/apiStoryClient.ts'
import { storyClientMode } from '../src/services/storyClient.ts'

const fridge = projects.find(p => p.id === 'fridge')!
const cloud = projects.find(p => p.id === 'cloud')!
type Call = { url: string; headers: Record<string, string>; body: any }

function fakeBackend(project = fridge, overrides: Partial<Record<string, (body: any) => Response>> = {}) {
  const calls: Call[] = []
  let completed = 0
  const fetch = async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? '{}'))
    calls.push({ url, headers: init?.headers as Record<string, string>, body })
    const key = url.endsWith('/turns') ? 'turn' : url.endsWith('/conversations') ? 'conversation' : 'session'
    if (overrides[key]) return overrides[key]!(body)
    if (key === 'session') return Response.json({ personal_code: 'CODE-1234' }, { status: 201 })
    if (key === 'conversation') return Response.json({ conversation_id: 'conv-1', project: body.project, completed_turns: 0, total_turns: project.steps.length, finished: false }, { status: 201 })
    const replayed = body.turn < completed
    if (!replayed) completed = body.turn + 1
    return Response.json({ conversation_id: 'conv-1', project: project.id, request_id: body.request_id, turn: body.turn, replies: [{ speaker: project.steps[body.turn].speaker, text: '서버 응답' }], reaction: '흠흠…', provider: 'gemini', model: 'gemini-test', latency_ms: 812, completed_turns: body.turn + 1, total_turns: project.steps.length, finished: body.turn + 1 === project.steps.length, replayed })
  }
  return { calls, fetch }
}

const signal = () => new AbortController().signal

test('세션·대화는 한 번만 만들고 개인 코드와 선택지 ID로 턴을 보낸다', async () => {
  const backend = fakeBackend()
  const client = createApiStoryClient({ displayName: '민트', fetch: backend.fetch })
  const first = await client.sendTurn({ requestId: 'req-0000-aaaa', project: fridge, turn: 0, input: { text: fridge.steps[0].choices[1].label, choice: 1 } }, signal())
  assert.equal(first.text, '서버 응답')
  assert.deepEqual(first.meta, { provider: 'gemini', model: 'gemini-test', latencyMs: 812, replayed: false, finished: false })
  await client.sendTurn({ requestId: 'req-0001-bbbb', project: fridge, turn: 1, input: { text: '자유 입력' } }, signal())
  assert.deepEqual(backend.calls.map(c => c.url), ['/api/sessions', '/api/story-chat/conversations', '/api/story-chat/conversations/conv-1/turns', '/api/story-chat/conversations/conv-1/turns'])
  assert.deepEqual(backend.calls[0].body, { display_name: '민트' })
  assert.deepEqual(backend.calls[2].body, { request_id: 'req-0000-aaaa', turn: 0, input: { text: fridge.steps[0].choices[1].label, choice_id: 'fridge-01-b' } })
  assert.deepEqual(backend.calls[3].body.input, { text: '자유 입력' })
  for (const call of backend.calls) {
    assert.deepEqual(Object.keys(call.headers).filter(h => h !== 'Content-Type'), call.url === '/api/sessions' ? [] : ['X-Personal-Code'])
  }
})

test('같은 requestId 재시도는 그대로 전송되고 서버 재생 응답을 받는다', async () => {
  let failures = 1
  const backend = fakeBackend(fridge)
  const flaky = async (url: string, init?: RequestInit) => {
    if (url.endsWith('/turns') && failures-- > 0) return new Response('{"detail":"AI 응답 생성에 실패했습니다."}', { status: 502 })
    return backend.fetch(url, init)
  }
  const client = createApiStoryClient({ displayName: '민트', fetch: flaky })
  const request = { requestId: 'retry-stable-0001', project: fridge, turn: 0, input: { text: '안녕' } }
  await assert.rejects(client.sendTurn(request, signal()), (error: unknown) => error instanceof StoryApiError && error.kind === 'server' && error.status === 502)
  const ok = await client.sendTurn(request, signal())
  assert.equal(ok.speaker, '냉장고 회장')
  const turnBodies = backend.calls.filter(c => c.url.endsWith('/turns')).map(c => c.body.request_id)
  assert.deepEqual(turnBodies, ['retry-stable-0001'])
  assert.equal(backend.calls.filter(c => c.url === '/api/sessions').length, 1)
})

test('세션 생성이 실패하면 다음 시도에서 다시 만든다', async () => {
  let down = true
  const backend = fakeBackend()
  const client = createApiStoryClient({ displayName: '민트', fetch: async (url, init) => { if (down) throw new TypeError('fetch failed'); return backend.fetch(url, init) } })
  const request = { requestId: 'req-network-01', project: fridge, turn: 0, input: { text: '안녕' } }
  await assert.rejects(client.sendTurn(request, signal()), (error: unknown) => error instanceof StoryApiError && error.kind === 'network')
  down = false
  assert.equal((await client.sendTurn(request, signal())).text, '서버 응답')
})

test('서버 진행 장면과 응답 장면이 다르면 진행하지 않는다', () => {
  const base = { request_id: 'r-1', turn: 2, completed_turns: 3, replies: [{ speaker: '냉장고 회장', text: '응답' }], provider: 'gemini', model: 'm' }
  assert.equal(parseStoryTurnResponse(base, { requestId: 'r-1', turn: 2 }).text, '응답')
  assert.throws(() => parseStoryTurnResponse({ ...base, completed_turns: 4 }, { requestId: 'r-1', turn: 2 }), (e: unknown) => e instanceof StoryApiError && e.kind === 'conflict')
  assert.throws(() => parseStoryTurnResponse({ ...base, request_id: 'other' }, { requestId: 'r-1', turn: 2 }), (e: unknown) => e instanceof StoryApiError && e.kind === 'conflict')
  assert.throws(() => parseStoryTurnResponse({ ...base, replies: [] }, { requestId: 'r-1', turn: 2 }), (e: unknown) => e instanceof StoryApiError && e.kind === 'invalid')
})

test('409와 구름섬 다중 화자 응답을 구분해 처리한다', async () => {
  const conflict = fakeBackend(cloud, { turn: () => Response.json({ detail: { message: 'x', current_turn: 1 } }, { status: 409 }) })
  const client = createApiStoryClient({ displayName: '구름', fetch: conflict.fetch })
  await assert.rejects(client.sendTurn({ requestId: 'req-conflict-1', project: cloud, turn: 0, input: { text: '가자' } }, signal()), (e: unknown) => e instanceof StoryApiError && e.kind === 'conflict')

  const multi = fakeBackend(cloud, { turn: body => Response.json({ request_id: body.request_id, turn: 0, completed_turns: 1, replies: [{ speaker: '토토', text: '가자!' }, { speaker: '나나', text: '괜찮아?' }], reaction: '함께하는 용기', provider: 'mock', model: 'mock-story-v1', latency_ms: 0 }) })
  const reply = await createApiStoryClient({ displayName: '구름', fetch: multi.fetch }).sendTurn({ requestId: 'req-multi-01', project: cloud, turn: 0, input: { text: cloud.steps[0].choices[0].label, choice: 0 } }, signal())
  assert.equal(reply.speaker, '토토')
  assert.deepEqual(reply.followUps, [{ speaker: '나나', text: '괜찮아?' }])
  assert.equal(reply.meta?.provider, 'mock')
  assert.equal(multi.calls.at(-1)!.body.input.choice_id, 'cloud-01-a')
})

test('사용자 취소와 시간 초과를 구분한다', async () => {
  const hanging = (_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  const cancelled = new AbortController()
  const pending = createApiStoryClient({ displayName: '민트', fetch: hanging }).sendTurn({ requestId: 'req-cancel-01', project: fridge, turn: 0, input: { text: '안녕' } }, cancelled.signal)
  cancelled.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  await assert.rejects(createApiStoryClient({ displayName: '민트', fetch: hanging, timeoutMs: 20 }).sendTurn({ requestId: 'req-timeout-1', project: fridge, turn: 0, input: { text: '안녕' } }, signal()), (e: unknown) => e instanceof StoryApiError && e.kind === 'timeout')
})

test('선택지 ID 규칙과 기본 Mock 모드', () => {
  assert.equal(storyChoiceId('fridge', 9, 1), 'fridge-10-b')
  assert.equal(storyChoiceId('cloud', 0, 0), 'cloud-01-a')
  assert.equal(storyClientMode(), 'mock')
})
