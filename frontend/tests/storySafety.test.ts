import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isCrisisText } from '../src/services/crisisSafety.ts'
import { parseStoryTurnResponse, StoryApiError } from '../src/services/apiStoryClient.ts'

test('위기 신호 표현은 띄어쓰기와 무관하게 감지한다', () => {
  for (const text of ['죽고 싶다', '죽고싶어요', '그냥 사라지고 싶어', '자해하고 싶다', '다 끝내고 싶다', '살기 싫어', '살고 싶지 않아', '자살']) assert.equal(isCrisisText(text), true, text)
})

test('일반적인 힘든 이야기와 평범한 입력은 감지하지 않는다', () => {
  for (const text of ['면접 또 떨어졌어요', '요즘 너무 지쳐요', '냉장고 문 열어도 돼요?', '오늘 일 끝내고 싶다', '아이스크림 먹고 싶어', '']) assert.equal(isCrisisText(text), false, text)
})

test('서버의 위기 안내 응답은 장면을 진행하지 않는 safety 응답으로 읽는다', () => {
  const body = { request_id: 'req-12345678', turn: 2, completed_turns: 2, replies: [{ speaker: '나나', text: '…말해 줘서 고마워.' }], provider: 'safety', model: 'crisis-notice-v1', safety_notice: true }
  const reply = parseStoryTurnResponse(body, { requestId: 'req-12345678', turn: 2 })
  assert.equal(reply.safety, true)
  assert.equal(reply.speaker, '나나')
})

test('위기 안내 응답이 장면을 진행했다고 주장하면 충돌로 처리한다', () => {
  const body = { request_id: 'req-12345678', turn: 2, completed_turns: 3, replies: [], provider: 'safety', model: 'm', safety_notice: true }
  assert.throws(() => parseStoryTurnResponse(body, { requestId: 'req-12345678', turn: 2 }), (e: unknown) => e instanceof StoryApiError && e.kind === 'conflict')
})
