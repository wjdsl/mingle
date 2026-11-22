import { test } from 'node:test'
import assert from 'node:assert/strict'
import { chatReducer, initialState } from '../src/features/chat/chatReducer.ts'
import { resolveMock } from '../src/services/mockConversationClient.ts'
import { SCENES, TOTAL_TURNS, PURUMA_ENDINGS } from '../src/projects/puruma/scenes.ts'
import { createPurumaStoryClient, parsePromo, purumaStoryMode } from '../src/services/apiPurumaStoryClient.ts'
import { createUserNoteStore } from '../src/services/userNoteStore.ts'
import { ENDINGS, loadAcquired, recordEnding } from '../src/services/endingCollection.ts'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
function memoryStorage() {
  const data = new Map<string, string>()
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) } }
}
const note = { key: 'interest:그림', field: 'interest', value: '그림', importance: 'medium', created_at_turn: 1, updated_at_turn: 1 }

test('장면: 10턴, 6구간, 턴마다 선택지와 자유 입력 대사가 있다', () => {
  assert.equal(TOTAL_TURNS, 10)
  assert.deepEqual([...new Set(SCENES.map(s => s.section))], [1, 2, 3, 4, 5, 6])
  for (const scene of SCENES) assert.ok(scene.choices.length >= 3 && scene.freeReply && scene.opening.length >= 1)
  assert.equal(new Set(SCENES.flatMap(s => s.choices.map(c => c.id))).size, SCENES.flatMap(s => s.choices).length)
})

test('브라우저 Mock: 선택지 반응·감정과 자유 입력 대사를 돌려주고 판정·홍보는 없다', () => {
  const choice = SCENES[2].choices[0]
  assert.deepEqual(resolveMock({ requestId: 'a', turn: 3, input: { kind: 'choice', choiceId: choice.id, text: choice.label } }), { text: choice.reply, emotion: choice.emotion })
  assert.deepEqual(resolveMock({ requestId: 'b', turn: 10, input: { kind: 'text', text: '창업' } }), { text: SCENES[9].freeReply, emotion: SCENES[9].freeEmotion })
  assert.throws(() => resolveMock({ requestId: 'c', turn: 2, input: { kind: 'choice', choiceId: choice.id, text: choice.label } }))
  assert.throws(() => resolveMock({ requestId: 'd', turn: 11, input: { kind: 'text', text: '안녕' } }))
})

test('모드: VITE_PURUMA_CLIENT로 mock·scenario-mock·api를 고른다', () => {
  assert.equal(purumaStoryMode({ VITE_PURUMA_CLIENT: 'api' }), 'api')
  assert.equal(purumaStoryMode({ VITE_PURUMA_CLIENT: 'scenario-mock' }), 'scenario-mock')
  for (const env of [undefined, {}, { VITE_PURUMA_CLIENT: 'API' }, { VITE_STORY_CLIENT: 'api' }]) assert.equal(purumaStoryMode(env), 'mock')
})

test('홍보 카드: https 공식 URL만 받는다', () => {
  assert.deepEqual(parsePromo({ id: 'rag_x', url: 'https://www.yu.ac.kr/a', label: '안내', source_name: '영남대' }), { id: 'rag_x', url: 'https://www.yu.ac.kr/a', label: '안내', sourceName: '영남대' })
  assert.equal(parsePromo({ id: 'x', url: 'javascript:alert(1)' }), undefined)
  assert.equal(parsePromo(null), undefined)
})

test('서버 클라이언트: 세션·대화를 만들고 턴·기억·홍보·엔딩을 주고받는다', async () => {
  const calls: { path: string; body: any; headers: any }[] = []
  const storage = memoryStorage()
  const store = createUserNoteStore(() => storage)
  store.write([note])
  const fetch = async (path: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? '{}'))
    calls.push({ path, body, headers: init?.headers })
    if (path === '/api/sessions') return json({ personal_code: 'CODE-1' }, 201)
    if (path === '/api/story-chat/conversations') return json({ conversation_id: 'conv-1', project: 'puruma', total_turns: 10 }, 201)
    return json({ turn: body.turn, replies: [{ speaker: '푸르마', text: '학식이요?' }, { speaker: '푸르마', text: '히히힝!' }], provider: 'mock', emotion: 'sparkle',
      promo: { id: 'rag_dining_cafeteria_menu', url: 'https://www.yu.ac.kr/main/life/cafeteria-menu.do', label: '구내식당', source_name: '영남대' },
      notes: [note, { ...note, key: 'section_choice:s2', field: 'section_choice', value: '적응: 맛있는 밥' }], finished: body.turn === 9, ending: body.turn === 9 ? 'cc_pruma' : null })
  }
  const client = createPurumaStoryClient({ displayName: '민트', provider: 'mock', fetch, store })
  const response = await client.sendTurn({ requestId: 'req-00000001', turn: 3, input: { kind: 'choice', choiceId: 'c2_t3_a', text: '맛있는 밥' } })
  assert.equal(response.text, '학식이요?\n히히힝!')
  assert.equal(response.emotion, 'sparkle')
  assert.equal(response.promo?.id, 'rag_dining_cafeteria_menu')
  assert.equal(response.ending, null)
  const turnCall = calls.at(-1)!
  assert.equal(turnCall.path, '/api/story-chat/conversations/conv-1/turns')
  assert.deepEqual(turnCall.body.input, { text: '맛있는 밥', choice_id: 'c2_t3_a' })
  assert.equal(turnCall.body.turn, 2)
  assert.deepEqual(turnCall.body.notes, [note])
  assert.equal(turnCall.headers['X-Story-Provider'], 'mock')
  assert.equal(store.read().length, 2)
  // 같은 requestId 재시도는 다시 보내지 않는다.
  await client.sendTurn({ requestId: 'req-00000001', turn: 3, input: { kind: 'choice', choiceId: 'c2_t3_a', text: '맛있는 밥' } })
  assert.equal(calls.filter(c => c.path.endsWith('/turns')).length, 1)
  const last = await client.sendTurn({ requestId: 'req-00000010', turn: 10, input: { kind: 'text', text: '창업' } })
  assert.equal(last.ending, 'cc_pruma')
  assert.equal(calls.filter(c => c.path === '/api/sessions').length, 1)
})

test('서버 클라이언트: 위기 안내 응답은 기억을 덮어쓰지 않고 오류는 Mock으로 대체하지 않는다', async () => {
  const storage = memoryStorage()
  const store = createUserNoteStore(() => storage)
  store.write([note])
  let mode: 'safety' | 'error' = 'safety'
  const fetch = async (path: string) => {
    if (path === '/api/sessions') return json({ personal_code: 'CODE-1' }, 201)
    if (path === '/api/story-chat/conversations') return json({ conversation_id: 'conv-1', project: 'puruma' }, 201)
    return mode === 'safety' ? json({ turn: 0, safety_notice: true, replies: [{ speaker: '푸르마', text: '말해 줘서 고마워요.' }], notes: [] }) : json({ detail: 'x' }, 502)
  }
  const client = createPurumaStoryClient({ displayName: '민트', provider: 'gemini', fetch, store })
  const safety = await client.sendTurn({ requestId: 'req-crisis-1', turn: 1, input: { kind: 'text', text: '...' } })
  assert.equal(safety.safety, true)
  assert.deepEqual(store.read(), [note])
  mode = 'error'
  await assert.rejects(client.sendTurn({ requestId: 'req-error-01', turn: 1, input: { kind: 'text', text: '안녕' } }))
  assert.match(client.lastErrorMessage(), /AI 응답/)
})

test('엔딩 도감: 푸르마 6종만 기록하고 위기·Mock 결과는 기록하지 않는다', () => {
  assert.deepEqual(ENDINGS.puruma.map(e => e.id), PURUMA_ENDINGS.map(e => e.id))
  const storage = memoryStorage()
  assert.equal(recordEnding('puruma', 'preview-survivor', storage), false)
  assert.equal(recordEnding('puruma', 'cc_pruma', storage), true)
  assert.deepEqual(loadAcquired('puruma', storage), ['cc_pruma'])
})

test('위기 입력 뒤에도 진행 턴은 그대로다', () => {
  const state = chatReducer(initialState(), { type: 'crisis', id: 'c', text: '죽고 싶어' })
  assert.equal(state.completedTurns, 0)
  assert.equal(state.messages.length, 4)
})

test('이어하기: 새 대화에서만 저장된 턴의 첫 대사부터 복원하고 범위 밖은 무시한다', () => {
  const restored = chatReducer(initialState(), { type: 'restore', turn: 4 })
  assert.equal(restored.completedTurns, 4)
  assert.equal(restored.resumedFrom, 4)
  assert.equal(restored.messages.length, 1)
  assert.equal(restored.messages[0].text, SCENES[4].opening.join('\n'))
  assert.equal(chatReducer(initialState(), { type: 'restore', turn: 0 }).completedTurns, 0)
  assert.equal(chatReducer(initialState(), { type: 'restore', turn: TOTAL_TURNS }).completedTurns, 0)
  assert.equal(chatReducer(restored, { type: 'restore', turn: 6 }), restored)
  const next = chatReducer(restored, { type: 'send', request: { requestId: 'r5', turn: 5, input: { kind: 'text', text: '같이 하자' } } })
  assert.equal(next.status, 'responding')
})

test('이어하기: 서버 클라이언트는 저장된 대화를 그대로 쓰고 진행 턴을 GET으로 확인한다', async () => {
  const calls: { path: string; method?: string }[] = []
  const fetch = async (path: string, init?: RequestInit) => {
    calls.push({ path, method: init?.method })
    if (path === '/api/story-chat/conversations/conv-9') return json({ conversation_id: 'conv-9', project: 'puruma', completed_turns: 3, total_turns: 10, finished: false })
    return json({ turn: 3, replies: [{ speaker: '푸르마', text: '좋아요!' }], emotion: 'happy', notes: [] })
  }
  const client = createPurumaStoryClient({ displayName: '민트', provider: 'mock', fetch, store: createUserNoteStore(() => memoryStorage()), resume: { code: 'CODE-9', conversationId: 'conv-9' } })
  assert.deepEqual(client.session(), { code: 'CODE-9', conversationId: 'conv-9' })
  assert.deepEqual(await client.progress(), { completedTurns: 3, totalTurns: 10, finished: false })
  await client.sendTurn({ requestId: 'req-resume-4', turn: 4, input: { kind: 'text', text: '좋아' } })
  assert.deepEqual(calls.map(c => c.path), ['/api/story-chat/conversations/conv-9', '/api/story-chat/conversations/conv-9/turns'])
  assert.equal(calls[0].method, 'GET')
  client.reset()
  assert.equal(client.session(), null)
})
