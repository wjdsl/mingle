import { test } from 'node:test'
import assert from 'node:assert/strict'
import { PENDING_MESSAGES, PENDING_SLOW_MS, PENDING_VERY_SLOW_MS, pendingLevel } from '../src/features/chat/pendingText.ts'

test('실제 경과 시간에 따라 0 → 1 → 2 단계로만 바뀐다', () => {
  assert.equal(pendingLevel(0), 0)
  assert.equal(pendingLevel(PENDING_SLOW_MS - 1), 0)
  assert.equal(pendingLevel(PENDING_SLOW_MS), 1)
  assert.equal(pendingLevel(PENDING_VERY_SLOW_MS - 1), 1)
  assert.equal(pendingLevel(PENDING_VERY_SLOW_MS), 2)
  assert.equal(pendingLevel(10 * 60_000), 2)
})
test('문구는 승인된 3개이며 진행률·예상 시간·숫자를 포함하지 않는다', () => {
  assert.deepEqual(Object.values(PENDING_MESSAGES), [
    '푸르마가 생각하고 있어요',
    '평소보다 시간이 걸리고 있어요. 답변을 기다리는 중이에요.',
    '아직 답변을 기다리고 있어요. 연결 상태에 따라 시간이 더 걸릴 수 있어요.',
  ])
  for (const text of Object.values(PENDING_MESSAGES)) assert.ok(!/\d|%|초|분 /.test(text))
})
