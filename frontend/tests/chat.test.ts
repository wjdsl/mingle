import { test } from 'node:test'
import assert from 'node:assert/strict'
import { chatReducer, initialState, validateInput } from '../src/features/chat/chatReducer.ts'

const request = { requestId: 'one', turn: 1, input: { kind: 'text' as const, text: '같이 가자' } }
const response = { text: '고마워요!', emotion: 'happy' as const }

test('공백·300자 경계와 이모지 길이를 검사한다', () => {
  assert.ok(validateInput('   '))
  assert.equal(validateInput('가'.repeat(300)), null)
  assert.ok(validateInput('가'.repeat(301)))
  assert.equal(validateInput('😀'.repeat(300)), null)
})
test('전송 중 중복 요청과 오래된 응답은 대화·진행에 반영하지 않는다', () => {
  const pending = chatReducer(initialState(), { type: 'send', request })
  assert.equal(pending.messages.length, 2)
  assert.equal(pending.completedTurns, 0)
  assert.equal(chatReducer(pending, { type: 'send', request }), pending)
  assert.equal(chatReducer(pending, { type: 'success', requestId: 'stale', response }), pending)
  const success = chatReducer(pending, { type: 'success', requestId: 'one', response })
  assert.equal(success.completedTurns, 1)
  assert.equal(chatReducer(success, { type: 'success', requestId: 'one', response }), success)
})
test('실패·재시도는 사용자 메시지와 턴을 중복 생성하지 않는다', () => {
  const pending = chatReducer(initialState(), { type: 'send', request })
  const failed = chatReducer(pending, { type: 'failure', requestId: 'one' })
  assert.equal(failed.completedTurns, 0)
  const retry = chatReducer(failed, { type: 'retry' })
  assert.equal(retry.messages.length, 2)
  assert.equal(retry.pending?.requestId, 'one')
  const success = chatReducer(retry, { type: 'success', requestId: 'one', response })
  assert.equal(success.messages.length, 3)
  assert.equal(success.completedTurns, 1)
})
test('2턴 시연 종료 후 추가 전송을 막고 다시 시작하면 초기화한다', () => {
  const first = chatReducer(chatReducer(initialState(), { type: 'send', request }), { type: 'success', requestId: 'one', response })
  const secondRequest = { ...request, requestId: 'two', turn: 2 }
  const final = chatReducer(chatReducer(first, { type: 'send', request: secondRequest }), { type: 'success', requestId: 'two', response })
  assert.equal(final.status, 'complete')
  assert.equal(final.completedTurns, 2)
  assert.equal(final.messages.length, 5)
  assert.equal(chatReducer(final, { type: 'send', request: { ...request, turn: 3 } }), final)
  assert.deepEqual(chatReducer(final, { type: 'reset' }), initialState())
})

test('이전 메시지의 감정은 다음 턴 반응이 바뀌어도 유지한다', () => {
  const first = chatReducer(chatReducer(initialState(), { type: 'send', request }), { type: 'success', requestId: 'one', response })
  const next = { ...request, requestId: 'two', turn: 2 }
  const final = chatReducer(chatReducer(first, { type: 'send', request: next }), {
    type: 'success', requestId: 'two', response: { text: '또각!', emotion: 'sparkle' },
  })
  assert.deepEqual(final.messages.filter(message => message.role === 'character').map(message => message.emotion), ['confused', 'happy', 'sparkle'])
  assert.equal(final.emotion, 'sparkle')
})

// 실제 네트워크 대신 fetch를 대체해 오류와 동일 요청 재전송을 확인한다.
import { geminiConversationClient, parseTurnResponse } from '../src/services/geminiConversationClient.ts'

test('Gemini 응답의 감정·빈 대사·형식을 검증한다', () => {
  assert.deepEqual(parseTurnResponse(response), response)
  for (const value of [null, { text: ' ', emotion: 'happy' }, { text: '안녕', emotion: 'angry' }, { ...response, extra: 1 }]) {
    assert.throws(() => parseTurnResponse(value))
  }
})

test('Gemini 실패 뒤 재시도는 같은 요청을 전송한다', async () => {
  const original = globalThis.fetch
  const bodies: string[] = []
  globalThis.fetch = async (_url, options) => {
    bodies.push(String(options?.body))
    return bodies.length === 1 ? new Response('', { status: 502 }) : Response.json(response)
  }
  try {
    await assert.rejects(geminiConversationClient.sendTurn(request))
    assert.deepEqual(await geminiConversationClient.sendTurn(request), response)
    assert.equal(bodies[0], bodies[1])
  } finally { globalThis.fetch = original }
})

test('응답 대기와 실패 후에도 원래 입력·맥락·진행을 보존한다', () => {
  const fullRequest = { ...request, history: [{ role: 'character' as const, text: '강의실이 어디죠?' }] }
  const waiting = chatReducer(initialState(), { type: 'send', request: fullRequest })
  assert.equal(waiting.status, 'responding')
  assert.equal(waiting.pending, fullRequest)
  const failed = chatReducer(waiting, { type: 'failure', requestId: 'one' })
  assert.equal(failed.pending, fullRequest)
  assert.equal(failed.messages, waiting.messages)
  assert.equal(failed.completedTurns, 0)
  const retry = chatReducer(failed, { type: 'retry' })
  assert.equal(retry.status, 'responding')
  assert.equal(retry.pending, fullRequest)
})


test('Gemini는 개발 제한 135초와 외부 취소 신호를 적용한다', async () => {
  const originalFetch = globalThis.fetch
  const originalTimeout = AbortSignal.timeout
  const timeoutController = new AbortController()
  const external = new AbortController()
  AbortSignal.timeout = (milliseconds) => {
    assert.equal(milliseconds, 135000)
    return timeoutController.signal
  }
  globalThis.fetch = async (_url, options) => {
    const signal = options?.signal
    assert.ok(signal)
    assert.equal(signal.aborted, false)
    external.abort()
    assert.equal(signal.aborted, true)
    return Response.json(response)
  }
  try {
    await geminiConversationClient.sendTurn(request, external.signal)
  } finally {
    globalThis.fetch = originalFetch
    AbortSignal.timeout = originalTimeout
  }
})
