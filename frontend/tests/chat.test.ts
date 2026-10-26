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
