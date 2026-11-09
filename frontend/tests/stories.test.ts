import { test } from 'node:test'
import assert from 'node:assert/strict'
import { projects } from '../src/projects/stories/catalog.ts'
import { requestStoryReply } from '../src/services/mockStoryClient.ts'

const fridge = projects.find(p => p.id === 'fridge')!
const cloud = projects.find(p => p.id === 'cloud')!

test('선택 응답과 자유 입력용 고정 응답을 구분하고 다중 캐릭터의 화자를 보존한다', async () => {
  const signal = new AbortController().signal
  const choice = await requestStoryReply(fridge, 0, 0, signal)
  const free = await requestStoryReply(fridge, 0, undefined, signal)
  assert.notEqual(choice.text, free.text)
  assert.equal(choice.speaker, '냉장고 회장')
  const teammate = await requestStoryReply(cloud, 0, 0, signal)
  assert.equal(teammate.speaker, '나나')
  assert.ok(!teammate.text.startsWith('나나:'))
})

test('이미 취소되거나 대기 중 취소된 Mock 요청은 결과를 반환하지 않는다', async () => {
  const cancelled = new AbortController()
  cancelled.abort()
  await assert.rejects(requestStoryReply(cloud, 0, 0, cancelled.signal), { name: 'AbortError' })
  const pending = new AbortController()
  const request = requestStoryReply(cloud, 0, 0, pending.signal)
  pending.abort()
  await assert.rejects(request, { name: 'AbortError' })
})

test('Mock 실패 뒤 동일한 입력을 재시도할 수 있다', async () => {
  const signal = new AbortController().signal
  await assert.rejects(requestStoryReply(fridge, 1, 0, signal, true), /Mock 응답 실패/)
  const response = await requestStoryReply(fridge, 1, 0, signal)
  assert.ok(response.text.length > 0)
  assert.equal(response.speaker, '냉장고 회장')
})
