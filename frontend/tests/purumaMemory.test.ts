import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createUserNoteStore, USER_NOTE_STORAGE_KEY, MAX_USER_NOTES } from '../src/services/userNoteStore.ts'
import { createApiChatClient, errorKindForStatus, purumaClientMode } from '../src/services/apiChatClient.ts'

const note = (key: string, value = '음악') => ({ key, field: 'interest', value, importance: 'medium', created_at_turn: 1, updated_at_turn: 1 })
function fakeStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) } }
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const req = (requestId: string, text = '안녕') => ({ requestId, turn: 1, input: { kind: 'text' as const, text } })

test('저장소: 키·버전·최대 10개를 지키고 손상된 값은 빈 목록이다', () => {
  const storage = fakeStorage()
  const store = createUserNoteStore(() => storage)
  assert.deepEqual(store.read(), [])
  store.write(Array.from({ length: 12 }, (_, i) => note(`interest:${i}`)))
  assert.equal(store.read().length, MAX_USER_NOTES)
  assert.equal(JSON.parse(storage.data.get(USER_NOTE_STORAGE_KEY)!).version, 1)
  storage.data.set(USER_NOTE_STORAGE_KEY, '{깨진 json')
  assert.deepEqual(store.read(), [])
  storage.data.set(USER_NOTE_STORAGE_KEY, JSON.stringify({ version: 2, notes: [note('a')] }))
  assert.deepEqual(store.read(), [])
  assert.equal(USER_NOTE_STORAGE_KEY, 'mingle:puruma:usernotes:v1')
})
test('저장소: 형식이 잘못된 항목은 걸러내고 저장 값에는 기억 목록만 있다', () => {
  const storage = fakeStorage()
  const store = createUserNoteStore(() => storage)
  store.write([note('ok'), { key: '', field: 'interest', value: 'x', importance: 'high' }, { key: 'k', field: 'f', value: 'x'.repeat(201), importance: 'high' }, 'x', null])
  assert.deepEqual(store.read().map(n => n.key), ['ok'])
  assert.deepEqual(Object.keys(JSON.parse(storage.data.get(USER_NOTE_STORAGE_KEY)!)).sort(), ['notes', 'version'])
})
test('저장소: localStorage가 예외를 던져도 안전하고 메모리로 동작하며 삭제된다', () => {
  const broken = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') }, removeItem() { throw new Error('denied') } }
  const store = createUserNoteStore(() => broken)
  assert.deepEqual(store.read(), [])
  store.write([note('a')])
  assert.deepEqual(store.read().map(n => n.key), ['a'])
  store.clear()
  assert.deepEqual(store.read(), [])
  const none = createUserNoteStore(() => null)
  none.write([note('b')]); assert.equal(none.read().length, 1)
})

test('환경변수: api일 때만 API 모드이고 기본은 Mock이다', () => {
  assert.equal(purumaClientMode({ VITE_PURUMA_CLIENT: 'api' }), 'api')
  for (const env of [undefined, {}, { VITE_PURUMA_CLIENT: 'mock' }, { VITE_PURUMA_CLIENT: 'API' }, { VITE_STORY_CLIENT: 'api' }]) assert.equal(purumaClientMode(env), 'mock')
})
test('상태 코드를 409·422·429·502로 구분한다', () => {
  assert.deepEqual([409, 422, 429, 502, 401, 500].map(errorKindForStatus), ['conflict', 'invalid', 'quota', 'server', 'auth', 'server'])
})

function setup(handler: (url: string, init: RequestInit, calls: { url: string; body: any; headers: any }[]) => Response, initial: unknown[] = []) {
  const storage = fakeStorage()
  const store = createUserNoteStore(() => storage)
  if (initial.length) store.write(initial)
  const calls: { url: string; body: any; headers: any }[] = []
  const fetch = async (url: string, init?: RequestInit) => {
    calls.push({ url, body: JSON.parse(String(init?.body)), headers: init?.headers })
    return handler(url, init!, calls)
  }
  return { client: createApiChatClient({ displayName: '콩', fetch, store }), store, calls, storage }
}
const sessionOk = () => json({ personal_code: 'SECRET-CODE', conversation: { id: 'c1' } }, 201)

test('API: 세션 생성 후 기억을 notes로 보내고 응답 notes를 저장하며 선택지 라벨을 message로 보낸다', async () => {
  const { client, store, calls, storage } = setup(url => url === '/api/sessions' ? sessionOk() : json({ reply: '지도 좋아요!', notes: [note('interest:음악')] }), [note('nickname', '콩')])
  const response = await client.sendTurn({ requestId: 'r1', turn: 1, input: { kind: 'choice', choiceId: 'map', text: '지도 같이 보자' } })
  assert.deepEqual(response, { text: '지도 좋아요!', emotion: 'happy' })
  assert.equal(calls[0].body.persona_slug, 'puruma')
  assert.equal(calls[1].body.message, '지도 같이 보자')
  assert.equal(calls[1].body.conversation_id, 'c1')
  assert.equal(calls[1].body.notes[0].key, 'nickname')
  assert.equal(calls[1].headers['X-Personal-Code'], 'SECRET-CODE')
  assert.deepEqual(store.read().map(n => n.key), ['interest:음악']) // 서버 notes가 정본
  const stored = storage.data.get(USER_NOTE_STORAGE_KEY)!
  assert.ok(!stored.includes('SECRET-CODE') && !stored.includes('c1') && !stored.includes('지도'))
})
test('API: 기억을 지우면 다음 요청은 빈 배열을 보낸다', async () => {
  const { client, store, calls } = setup(url => url === '/api/sessions' ? sessionOk() : json({ reply: '네!', notes: [] }), [note('a')])
  await client.sendTurn(req('r1'))
  assert.equal(calls[1].body.notes.length, 1)
  store.clear()
  await client.sendTurn(req('r2'))
  assert.deepEqual(calls[2].body.notes, [])
  assert.equal(calls.filter(c => c.url === '/api/sessions').length, 1) // 세션 재사용
})
test('API: 요청 중 기억을 지우면 늦게 온 응답이 기억을 되살리지 않는다', async () => {
  const { client, store } = setup(url => url === '/api/sessions' ? sessionOk() : json({ reply: '네', notes: [note('late')] }), [note('a')])
  const pending = client.sendTurn(req('r1'))
  store.clear()
  await pending
  assert.deepEqual(store.read(), [])
})
test('API: 오류는 Mock으로 대체하지 않고 종류별 메시지를 낸다', async () => {
  for (const [status, kind] of [[409, '끝난 대화'], [422, '요청 형식'], [429, '너무 많아요'], [502, 'AI 응답']] as const) {
    const { client, store } = setup(url => url === '/api/sessions' ? sessionOk() : json({ detail: 'x' }, status), [note('a')])
    await assert.rejects(client.sendTurn(req('r1')))
    assert.ok(client.lastErrorMessage().includes(kind), `${status}`)
    assert.deepEqual(store.read().map(n => n.key), ['a']) // 실패하면 기억을 바꾸지 않는다
  }
})
test('API: 네트워크 실패 후 재시도는 성공하고, 성공한 requestId는 서버에 다시 보내지 않는다', async () => {
  let fail = true
  const { client, calls } = setup(url => url === '/api/sessions' ? sessionOk() : json({ reply: '네', notes: [] }))
  const original = globalThis.fetch
  void original
  const flaky = createApiChatClient({ displayName: '콩', fetch: async (url, init) => { if (fail && url === '/api/chat') throw new TypeError('offline'); return url === '/api/sessions' ? sessionOk() : json({ reply: '네', notes: [] }) }, store: createUserNoteStore(() => null) })
  await assert.rejects(flaky.sendTurn(req('r1')))
  assert.ok(flaky.lastErrorMessage().includes('연결'))
  fail = false
  assert.equal((await flaky.sendTurn(req('r1'))).text, '네')
  const first = await client.sendTurn(req('r9'))
  assert.deepEqual(await client.sendTurn(req('r9')), first)
  assert.equal(calls.filter(c => c.url === '/api/chat').length, 1)
})
test('API: 응답 형식이 잘못되면 server 오류이며 기억을 바꾸지 않는다', async () => {
  const { client, store } = setup(url => url === '/api/sessions' ? sessionOk() : json({ reply: '' , notes: [note('x')] }), [note('a')])
  await assert.rejects(client.sendTurn(req('r1')))
  assert.deepEqual(store.read().map(n => n.key), ['a'])
})
test('API: reset하면 새 서버 대화를 만들고 기억은 유지한다', async () => {
  const { client, store, calls } = setup(url => url === '/api/sessions' ? sessionOk() : json({ reply: '네', notes: [note('k')] }))
  await client.sendTurn(req('r1'))
  client.reset()
  await client.sendTurn(req('r2'))
  assert.equal(calls.filter(c => c.url === '/api/sessions').length, 2)
  assert.deepEqual(store.read().map(n => n.key), ['k'])
})
