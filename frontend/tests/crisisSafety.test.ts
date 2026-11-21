import assert from 'node:assert/strict'
import test from 'node:test'
import { CRISIS_NOTICE, crisisCareLine, isCrisisText } from '../src/services/crisisSafety.ts'
import { chatReducer, initialState } from '../src/features/chat/chatReducer.ts'

test('자신을 해치려는 표현만 위기 신호로 본다 (띄어쓰기 무관)', () => {
  for (const text of ['죽고 싶어요', '죽고싶다', '그냥 사라지고 싶어', '자해했어', '살고 싶지 않아', '극단적 선택']) {
    assert.equal(isCrisisText(text), true, text)
  }
  for (const text of ['시험이 너무 힘들다', '다 포기하고 싶다', '면접 또 떨어졌어요', '요즘 너무 지쳐요', '']) {
    assert.equal(isCrisisText(text), false, text)
  }
})

test('안내 문구는 109와 119를 전화 링크로 제공한다', () => {
  assert.deepEqual(CRISIS_NOTICE.contacts.map(c => c.tel), ['tel:109', 'tel:119'])
})

test('캐릭터 반응은 작품별 고정 문장이다', () => {
  assert.equal(crisisCareLine('fridge').speaker, '냉장고 회장')
  assert.equal(crisisCareLine('cloud').speaker, '나나')
  assert.equal(crisisCareLine('puruma').speaker, '푸르마')
})

test('푸르마: 위기 입력은 턴을 진행하지 않고 안내와 차분한 반응만 붙인다', () => {
  const start = initialState()
  const next = chatReducer(start, { type: 'crisis', id: 'c1', text: '죽고 싶어요' })
  assert.equal(next.completedTurns, 0)
  assert.equal(next.status, 'idle')
  assert.equal(next.pending, null)
  assert.deepEqual(next.messages.slice(-3).map(m => m.role), ['user', 'notice', 'character'])
  assert.equal(next.messages.at(-1)?.calm, true)
  // 응답 대기 중에는 무시한다.
  const busy = { ...start, status: 'responding' as const }
  assert.equal(chatReducer(busy, { type: 'crisis', id: 'c2', text: '죽고 싶어요' }), busy)
})
