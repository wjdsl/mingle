import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createApiChatClient, ApiChatError } from '../src/services/apiChatClient.ts'
import { createUserNoteStore } from '../src/services/userNoteStore.ts'
import { chatReducer, initialState } from '../src/features/chat/chatReducer.ts'
import type { TurnRequest } from '../src/features/chat/types.ts'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const req = (requestId: string, turn = 1, text = '죽고 싶어요'): TurnRequest => ({ requestId, turn, input: { kind: 'text', text } })
function setup(chat: () => Response) {
  const writes: string[] = []
  const store = createUserNoteStore(() => ({ getItem: () => null, setItem: (_k: string, v: string) => { writes.push(v) }, removeItem() {} }))
  const fetch = async (url: string) => url.endsWith('/api/sessions') ? json({ personal_code: 'c', conversation: { id: 'x' } }) : chat()
  return { client: createApiChatClient({ displayName: '가', fetch, store }), writes }
}

test('정상 응답은 safety 없이 일반 응답으로 읽는다', async () => {
  const { client } = setup(() => json({ reply: '안녕하세요', notes: [], provider: 'mock' }))
  const response = await client.sendTurn(req('r1', 1, '안녕'))
  assert.equal(response.text, '안녕하세요')
  assert.equal(response.safety, undefined)
})

test('서버 safety_notice 응답은 오류가 아니라 안전 응답이며 기억을 쓰지 않는다 (notes 없음)', async () => {
  const { client, writes } = setup(() => json({ safety_notice: true, conversation_id: 'x', reply: '선배, 말해 줘서 고마워요.', provider: 'safety', state: {}, notes: null }))
  const response = await client.sendTurn(req('r2'))
  assert.equal(response.safety, true)
  assert.equal(response.text, '선배, 말해 줘서 고마워요.')
  assert.equal(writes.length, 0)
})

test('내용 없는 safety 응답과 서버 오류는 여전히 오류로 처리한다', async () => {
  const empty = setup(() => json({ safety_notice: true, reply: '  ' }))
  await assert.rejects(empty.client.sendTurn(req('r3')), (e: unknown) => e instanceof ApiChatError && e.kind === 'server')
  const failed = setup(() => json({ detail: 'x' }, 502))
  await assert.rejects(failed.client.sendTurn(req('r4')), (e: unknown) => e instanceof ApiChatError)
  const missing = setup(() => json({ reply: '안녕', provider: 'mock' })) // notes 없는 일반 응답은 기존처럼 오류
  await assert.rejects(missing.client.sendTurn(req('r5', 1, '안녕')), (e: unknown) => e instanceof ApiChatError && e.kind === 'server')
})

test('프론트 감지를 놓치고 서버만 감지한 경우: 턴·진행은 그대로이고 안내가 붙은 뒤 정상 대화를 이어 간다', async () => {
  const { client } = setup(() => json({ safety_notice: true, reply: '곁에 있을게요.', provider: 'safety', notes: null }))
  let state = chatReducer(initialState(), { type: 'send', request: req('c1') })
  const response = await client.sendTurn(req('c1'))
  state = chatReducer(state, { type: 'success', requestId: 'c1', response })
  assert.equal(state.completedTurns, 0)
  assert.equal(state.status, 'idle')
  assert.equal(state.pending, null)
  assert.equal(state.emotion, 'confused')
  assert.deepEqual(state.messages.slice(-3).map(m => m.role), ['user', 'notice', 'character'])
  assert.equal(state.messages.at(-1)?.text, '곁에 있을게요.')
  // 같은 턴 번호로 정상 입력을 이어 갈 수 있고 정상 성공은 턴을 올린다.
  state = chatReducer(state, { type: 'send', request: req('c2', 1, '오늘 시험 봤어요') })
  assert.equal(state.status, 'responding')
  state = chatReducer(state, { type: 'success', requestId: 'c2', response: { text: '수고했어요', emotion: 'happy' } })
  assert.equal(state.completedTurns, 1)
})
