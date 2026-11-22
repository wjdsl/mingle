import { test } from 'node:test'
import assert from 'node:assert/strict'
import { projects } from '../src/projects/stories/catalog.ts'
import { StoryApiError, createApiStoryClient, loadStoryScenario, parseStoryTurnResponse, storyChoiceId } from '../src/services/apiStoryClient.ts'
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
  const sentIds: string[] = []
  const backend = fakeBackend(fridge)
  const flaky = async (url: string, init?: RequestInit) => {
    if (url.endsWith('/turns')) {
      sentIds.push(JSON.parse(String(init?.body)).request_id)
      if (sentIds.length === 1) return Response.json({ detail: { code: 'gemini_unavailable' } }, { status: 503 })
    }
    return backend.fetch(url, init)
  }
  const client = createApiStoryClient({ displayName: '민트', fetch: flaky })
  const request = { requestId: 'retry-stable-0001', project: fridge, turn: 0, input: { text: '안녕' } }
  await assert.rejects(client.sendTurn(request, signal()), (error: unknown) => error instanceof StoryApiError && error.kind === 'server' && error.status === 503 && /잠시 후 같은 답변/.test(error.message))
  const ok = await client.sendTurn(request, signal())
  assert.equal(ok.speaker, '냉장고 회장')
  assert.equal((await client.sendTurn(request, signal())).meta?.replayed, true)
  assert.deepEqual(sentIds, ['retry-stable-0001', 'retry-stable-0001', 'retry-stable-0001'])
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

// 시나리오 장면 세트: 화면 표시용 선택지(호칭 치환)와 서버 검증용 원문 선택지를 분리한다.
function sceneSet(projectId: string, first: { label: string; opening: string }) {
  return {
    project: projectId, scene_set: 'scenario_draft_v1', total_turns: 10,
    scenes: Array.from({ length: 10 }, (_, turn) => ({
      turn, title: `장면 ${turn + 1}`, situation: '', input_mode: turn === 9 ? 'none' : 'input',
      opening_lines: [{ speaker: '화자', text: turn === 0 ? first.opening : '첫 대사' }], system_messages: [],
      choices: turn === 9 ? [] : [{ choice_id: `${projectId}_t${turn + 1}_btn`, label: turn === 0 ? first.label : `선택 ${turn + 1}` }],
    })),
  }
}

async function loadWith(project: typeof fridge, data: unknown, name: string) {
  const original = globalThis.fetch
  globalThis.fetch = (async () => Response.json(data)) as typeof fetch
  try { return await loadStoryScenario(project, name, signal()) } finally { globalThis.fetch = original }
}

test('시나리오 선택지는 호칭을 채워 표시하고 원문은 따로 보관한다', async () => {
  const raw = '(문을 닫으며) 죄송해요. 제 이름은 [호칭]입니다.'
  const loaded = await loadWith(fridge, sceneSet('fridge', { label: raw, opening: '잘 듣게, [호칭].' }), '민트')
  const choice = loaded.steps[0].choices[0]
  assert.equal(choice.label, '(문을 닫으며) 죄송해요. 제 이름은 민트입니다.')
  assert.equal(choice.sourceLabel, raw)
  assert.equal(loaded.steps[0].openingLines?.[0].text, '잘 듣게, 민트.')
  assert.deepEqual(loaded.steps[1].choices[0], { id: 'fridge_t2_btn', label: '선택 2', sourceLabel: '선택 2', reply: '', reaction: '' })
})

test('받침 유무와 관계없이 선택지 표시 문구가 자연스럽다', async () => {
  const raw = '(문을 닫으며) 죄송해요. 제 이름은 [호칭]입니다.'
  for (const name of ['민트', '민준']) {
    const loaded = await loadWith(fridge, sceneSet('fridge', { label: raw, opening: '첫 대사' }), name)
    assert.equal(loaded.steps[0].choices[0].label, `(문을 닫으며) 죄송해요. 제 이름은 ${name}입니다.`)
    assert.equal(loaded.steps[0].choices[0].sourceLabel, raw)
  }
})

test('선택지 전송은 서버 검증용 원문을, 자유 입력은 입력 그대로 보낸다', async () => {
  const raw = '(문을 닫으며) 죄송해요. 제 이름은 [호칭]입니다.'
  const loaded = await loadWith(fridge, sceneSet('fridge', { label: raw, opening: '첫 대사' }), '민트')
  const backend = fakeBackend(loaded)
  const client = createApiStoryClient({ displayName: '민트', fetch: backend.fetch })
  const shown = loaded.steps[0].choices[0].label
  await client.sendTurn({ requestId: 'req-0000-aaaa', project: loaded, turn: 0, input: { text: shown, choice: 0 } }, signal())
  await client.sendTurn({ requestId: 'req-0001-bbbb', project: loaded, turn: 1, input: { text: '저는 [호칭]이라고 불러 주세요' } }, signal())
  assert.deepEqual(backend.calls[2].body.input, { text: raw, choice_id: 'fridge_t1_btn' })
  assert.deepEqual(backend.calls[3].body.input, { text: '저는 [호칭]이라고 불러 주세요' })
})

test('냉장고 서버 장면은 구간 시작 4개 턴에만 표정 이미지를 붙인다', async () => {
  const loaded = await loadWith(fridge, sceneSet('fridge', { label: '선택', opening: '첫 대사' }), '민트')
  assert.deepEqual(loaded.steps.map(s => s.sceneImage), [
    'fridge-angry', undefined, undefined, undefined, undefined,
    'fridge-flustered', 'fridge-angry', undefined, undefined, 'fridge-smug',
  ])
  // 이어하기용: 그 턴까지 마지막으로 나온 표정
  assert.deepEqual(loaded.steps.map(s => s.expression), [
    'fridge-angry', 'fridge-angry', 'fridge-angry', 'fridge-angry', 'fridge-angry',
    'fridge-flustered', 'fridge-angry', 'fridge-angry', 'fridge-angry', 'fridge-smug',
  ])
  const sky = await loadWith(cloud, sceneSet('cloud', { label: '선택', opening: '첫 대사' }), '민트')
  // 구름섬은 첫 임무(1턴)에만 하늘섬 배경 이미지를 한 번 보여 주고, 표정(이어하기용)은 없다.
  assert.deepEqual(sky.steps.map(s => s.sceneImage), ['cloud-sky-islands', ...Array(9).fill(undefined)])
  assert.ok(sky.steps.every(s => s.expression === undefined))
})

test('구름섬 시나리오 선택지와 기본 Mock 선택지는 그대로다', async () => {
  const loaded = await loadWith(cloud, sceneSet('cloud', { label: '민트예요! 빨리 출동해요!', opening: '[닉네임], 반가워.' }), '민트')
  assert.equal(loaded.steps[0].choices[0].label, '민트예요! 빨리 출동해요!')
  assert.equal(loaded.steps[0].choices[0].sourceLabel, '민트예요! 빨리 출동해요!')
  assert.equal(loaded.steps[0].openingLines?.[0].text, '민트, 반가워.')
  for (const project of projects) for (const step of project.steps) for (const choice of step.choices) {
    assert.equal(choice.sourceLabel, undefined)
    assert.doesNotMatch(choice.label, /\[(호칭|닉네임)\]/)
  }
  // 원문이 없는 기본 Mock 선택지는 기존처럼 표시 문구를 그대로 보낸다.
  const backend = fakeBackend(cloud)
  const client = createApiStoryClient({ displayName: '민트', fetch: backend.fetch })
  await client.sendTurn({ requestId: 'req-0000-cccc', project: cloud, turn: 0, input: { text: cloud.steps[0].choices[0].label, choice: 0 } }, signal())
  assert.deepEqual(backend.calls[2].body.input, { text: cloud.steps[0].choices[0].label, choice_id: 'cloud-01-a' })
})

import { GEMINI_UNAVAILABLE_COOLDOWN_SECONDS, storyRetryPolicy } from '../src/services/apiStoryClient.ts'

async function failingTurn(response: () => Response) {
  const backend = fakeBackend(fridge, { turn: response })
  const client = createApiStoryClient({ displayName: '민트', fetch: backend.fetch })
  const error = await client.sendTurn({ requestId: 'req-policy-0001', project: fridge, turn: 0, input: { text: '안녕' } }, signal()).then(() => null, (e: unknown) => e)
  assert.ok(error instanceof StoryApiError)
  return error
}

test('Gemini 503은 15초 쿨타임 뒤 같은 요청으로 다시 시도하도록 안내한다', async () => {
  assert.equal(GEMINI_UNAVAILABLE_COOLDOWN_SECONDS, 15)
  const error = await failingTurn(() => Response.json({ detail: { code: 'gemini_unavailable' } }, { status: 503 }))
  assert.equal(error.status, 503)
  assert.equal(error.retryAfter, 15)
  assert.match(error.message, /15초 뒤 한 번만/)
  assert.deepEqual(storyRetryPolicy(error), { canRetry: true, waitSeconds: 15 })
})

test('429·504의 기존 재시도 정책에는 503 쿨타임을 적용하지 않는다', async () => {
  const minute = await failingTurn(() => Response.json({ detail: { code: 'gemini_quota_minute' } }, { status: 429, headers: { 'Retry-After': '7' } }))
  assert.deepEqual(storyRetryPolicy(minute), { canRetry: true, waitSeconds: 7 })
  const daily = await failingTurn(() => Response.json({ detail: { code: 'gemini_quota_daily' } }, { status: 429 }))
  assert.deepEqual(storyRetryPolicy(daily), { canRetry: true, waitSeconds: 0 })
  const timeout = await failingTurn(() => Response.json({ detail: 'Gemini 응답 시간이 초과되었습니다.' }, { status: 504 }))
  assert.equal(timeout.kind, 'timeout')
  assert.deepEqual(storyRetryPolicy(timeout), { canRetry: true, waitSeconds: 0 })
  const bad = await failingTurn(() => Response.json({ detail: 'x' }, { status: 502 }))
  assert.deepEqual(storyRetryPolicy(bad), { canRetry: true, waitSeconds: 0 })
  assert.deepEqual(storyRetryPolicy(new Error('Mock 응답 실패')), { canRetry: true, waitSeconds: 0 })
})

test('재시도해도 해결되지 않는 오류는 다시 시도를 제공하지 않는다', async () => {
  const mismatch = await failingTurn(() => Response.json({ detail: '요청한 스토리 공급자를 사용할 수 없습니다.' }, { status: 503 }))
  assert.equal(mismatch.retryAfter, undefined)
  assert.match(mismatch.message, /새로 시작/)
  assert.deepEqual(storyRetryPolicy(mismatch), { canRetry: false, waitSeconds: 0 })
  for (const status of [409, 401, 404]) {
    assert.equal(storyRetryPolicy(await failingTurn(() => Response.json({ detail: 'x' }, { status }))).canRetry, false)
  }
})

test('요청 검증 422는 재시도 불가이며 정상 응답의 형식 오류는 다시 시도할 수 있다', async () => {
  const rejected = await failingTurn(() => Response.json({ detail: '현재 장면의 선택지가 아닙니다.' }, { status: 422 }))
  assert.equal(rejected.kind, 'invalid')
  assert.equal(rejected.status, 422)
  assert.match(rejected.message, /새로 시작/)
  assert.deepEqual(storyRetryPolicy(rejected), { canRetry: false, waitSeconds: 0 })
  const pydantic = await failingTurn(() => Response.json({ detail: [{ type: 'string_too_short', loc: ['body', 'request_id'] }] }, { status: 422 }))
  assert.equal(storyRetryPolicy(pydantic).canRetry, false)
  const malformed = await failingTurn(() => Response.json({ unexpected: true }, { status: 200 }))
  assert.equal(malformed.kind, 'invalid')
  assert.deepEqual(storyRetryPolicy(malformed), { canRetry: true, waitSeconds: 0 })
  // 기존 정책은 그대로다.
  assert.deepEqual(storyRetryPolicy(await failingTurn(() => Response.json({ detail: { code: 'gemini_unavailable' } }, { status: 503 }))), { canRetry: true, waitSeconds: 15 })
  assert.deepEqual(storyRetryPolicy(await failingTurn(() => Response.json({ detail: 'x' }, { status: 504 }))), { canRetry: true, waitSeconds: 0 })
  assert.deepEqual(storyRetryPolicy(await failingTurn(() => Response.json({ detail: 'x' }, { status: 502 }))), { canRetry: true, waitSeconds: 0 })
})
