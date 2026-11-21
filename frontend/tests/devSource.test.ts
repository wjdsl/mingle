import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createApiChatClient } from '../src/services/apiChatClient.ts'
import { createUserNoteStore } from '../src/services/userNoteStore.ts'
import { describeTrace } from '../src/services/devSource.ts'
import { parseStoryTurnResponse } from '../src/services/apiStoryClient.ts'
import { withSourceTrace } from '../src/services/storyClient.ts'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const req = (requestId: string) => ({ requestId, turn: 1, input: { kind: 'text' as const, text: '안녕' } })
const store = () => createUserNoteStore(() => ({ getItem: () => null, setItem() {}, removeItem() {} }))

test('푸르마 API 클라이언트는 응답 provider를 기록한다(qwen)', async () => {
  const fetch = async (url: string) => url.endsWith('/api/sessions')
    ? json({ personal_code: 'c', conversation: { id: 'x' } })
    : json({ reply: '안녕하세요', notes: [], provider: 'qwen' })
  const client = createApiChatClient({ displayName: '가', fetch, store: store() })
  assert.equal((await client.sendTurn(req('r1'))).text, '안녕하세요')
  assert.equal(client.trace.provider, 'qwen')
  assert.match(describeTrace(client.trace), /^API · provider=qwen/)
})

test('푸르마 API 실패는 Mock으로 대체되지 않고 오류로 기록된다', async () => {
  const fetch = async (url: string) => url.endsWith('/api/sessions') ? json({ personal_code: 'c', conversation: { id: 'x' } }) : json({ detail: 'x' }, 502)
  const client = createApiChatClient({ displayName: '가', fetch, store: store() })
  await assert.rejects(client.sendTurn(req('r2')))
  assert.match(describeTrace(client.trace), /오류: server 502/)
  assert.equal(client.trace.provider, undefined)
})

test('Mock 출처는 MOCK으로 표시된다(스토리 mock 클라이언트 래퍼)', async () => {
  const client = withSourceTrace({ sendTurn: async () => ({ speaker: 'a', text: 't', reaction: 'r' }) }, 'mock')
  await client.sendTurn({} as never, new AbortController().signal)
  assert.match(describeTrace(client.trace), /^MOCK\(mock\) · provider=mock/)
})

test('스토리 래퍼는 meta의 provider·model을 기록하고 오류를 그대로 던진다', async () => {
  const ok = withSourceTrace({ sendTurn: async () => ({ speaker: 'a', text: 't', reaction: 'r', meta: { provider: 'gemini', model: 'g', latencyMs: 1, replayed: false, finished: false } }) }, 'api')
  await ok.sendTurn({} as never, new AbortController().signal)
  assert.match(describeTrace(ok.trace), /^API · provider=gemini model=g/)
  const bad = withSourceTrace({ sendTurn: async () => { throw new Error('boom') } }, 'api')
  await assert.rejects(bad.sendTurn({} as never, new AbortController().signal))
  assert.match(describeTrace(bad.trace), /오류/)
})

test('냉장고 응답은 대사에 사용한 공급자와 원본 대사를 쓴 이유를 표시한다', async () => {
  const request = { requestId: 'r1', turn: 0 }
  const response = {
    request_id: 'r1', turn: 0, completed_turns: 1, replies: [{ speaker: '회장', text: '흠흠.' }],
    provider: 'gemini', model: 'g', dialogue_provider: 'qwen',
  }
  const signal = new AbortController().signal
  let body: typeof response & { fallback_reason?: string } = response
  const client = withSourceTrace({ sendTurn: async () => parseStoryTurnResponse(body, request) }, 'api')

  await client.sendTurn({} as never, signal)
  assert.match(describeTrace(client.trace), /provider=gemini model=g · dialogue=qwen$/)

  body = { ...response, dialogue_provider: 'gemini', fallback_reason: 'qwen_connection' }
  await client.sendTurn({} as never, signal)
  assert.match(describeTrace(client.trace), /provider=gemini model=g · fallback=qwen_connection$/)
})
