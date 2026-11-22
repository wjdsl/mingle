import { test } from 'node:test'
import assert from 'node:assert/strict'
import { clearProgress, loadProgress, saveProgress } from '../src/services/storyProgress.ts'
import { ENDINGS, loadAcquired, recordEnding } from '../src/services/endingCollection.ts'
import { wrapText } from '../src/services/resultImage.ts'
import { createApiStoryClient } from '../src/services/apiStoryClient.ts'
import { projects } from '../src/projects/stories/catalog.ts'

function memoryStorage() {
  const data = new Map<string, string>()
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) }, data }
}

test('진행 저장: 호칭·완료 장면·서버 대화 정보만 저장하고 모드가 다르면 불러오지 않는다', () => {
  const storage = memoryStorage()
  saveProgress({ project: 'fridge', mode: 'api', name: '민트', completedTurns: 3, api: { code: 'CODE-1', conversationId: 'conv-1' } }, storage)
  const saved = loadProgress('fridge', 'api', storage)
  assert.equal(saved?.completedTurns, 3)
  assert.deepEqual(saved?.api, { code: 'CODE-1', conversationId: 'conv-1' })
  assert.deepEqual(Object.keys(saved!).sort(), ['api', 'completedTurns', 'mode', 'name', 'project', 'savedAt', 'v'])
  assert.equal(loadProgress('fridge', 'mock', storage), null)
  assert.equal(loadProgress('cloud', 'api', storage), null)
  clearProgress('fridge', storage)
  assert.equal(loadProgress('fridge', 'api', storage), null)
})

test('진행 저장: 깨진 값·저장소 없음·저장소 오류에도 예외 없이 동작한다', () => {
  const storage = memoryStorage()
  storage.setItem('mingle.progress.v1.cloud', '{broken')
  assert.equal(loadProgress('cloud', 'mock', storage), null)
  storage.setItem('mingle.progress.v1.cloud', JSON.stringify({ v: 1, project: 'cloud', mode: 'mock', name: 'x', completedTurns: -1 }))
  assert.equal(loadProgress('cloud', 'mock', storage), null)
  assert.equal(loadProgress('cloud', 'mock', null), null)
  const failing = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') } }
  assert.doesNotThrow(() => saveProgress({ project: 'cloud', mode: 'mock', name: 'x', completedTurns: 1 }, failing))
  assert.equal(loadProgress('cloud', 'mock', failing), null)
  assert.doesNotThrow(() => clearProgress('cloud', failing))
})

test('도감: 알려진 결말만 기록하고 중복 없이 순서대로 돌려준다', () => {
  const storage = memoryStorage()
  assert.deepEqual(loadAcquired('cloud', storage), [])
  assert.equal(recordEnding('cloud', 'cloud_result_kiki', storage), true)
  assert.equal(recordEnding('cloud', 'cloud_result_toto', storage), true)
  assert.equal(recordEnding('cloud', 'cloud_result_kiki', storage), true)
  assert.equal(recordEnding('cloud', 'not-an-ending', storage), false)
  assert.deepEqual(loadAcquired('cloud', storage), ['cloud_result_toto', 'cloud_result_kiki'])
  assert.deepEqual(loadAcquired('fridge', storage), [])
  assert.equal(ENDINGS.fridge.length, 3)
  assert.equal(ENDINGS.cloud.length, 5)
})

test('이미지 글 줄바꿈: 넓이를 넘으면 나누고 최대 줄 수에서 말줄임한다', () => {
  const measure = (s: string) => Array.from(s).length
  assert.deepEqual(wrapText('가나다라마바사', 3, measure), ['가나다', '라마바', '사'])
  assert.deepEqual(wrapText('ab cd ef', 5, measure), ['ab cd', 'ef'])
  assert.deepEqual(wrapText('첫 줄\n둘째', 10, measure), ['첫 줄', '둘째'])
  const cut = wrapText('가나다라마바사아자차', 3, measure, 2)
  assert.equal(cut.length, 2)
  assert.ok(cut[1].endsWith('…'))
})

test('API 이어하기: 저장된 대화로 서버 진행을 확인하고 새 세션을 만들지 않고 다음 장면을 보낸다', async () => {
  const fridge = projects.find(p => p.id === 'fridge')!
  const calls: { url: string; method: string; headers: Record<string, string> }[] = []
  const fetch = async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? 'GET', headers: init?.headers as Record<string, string> })
    if (init?.method === 'GET') return Response.json({ conversation_id: 'conv-9', project: 'fridge', completed_turns: 2, total_turns: fridge.steps.length, finished: false })
    const body = JSON.parse(String(init?.body))
    return Response.json({ conversation_id: 'conv-9', project: 'fridge', request_id: body.request_id, turn: body.turn, replies: [{ speaker: '냉장고 회장', text: '이어서 왔군.' }], reaction: '흠흠', completed_turns: body.turn + 1, provider: 'gemini', model: 'gemini-test', latency_ms: 1, finished: false })
  }
  const client = createApiStoryClient({ displayName: '민트', fetch, resume: { code: 'CODE-9', conversationId: 'conv-9', project: 'fridge', totalTurns: fridge.steps.length } })
  assert.deepEqual(client.session?.(), { code: 'CODE-9', conversationId: 'conv-9' })
  const progress = await client.progress?.(new AbortController().signal)
  assert.deepEqual(progress, { completedTurns: 2, totalTurns: fridge.steps.length, finished: false })
  const reply = await client.sendTurn({ requestId: 'req-resume-1', project: fridge, turn: 2, input: { text: '다시 왔어요' } }, new AbortController().signal)
  assert.equal(reply.text, '이어서 왔군.')
  assert.deepEqual(calls.map(c => `${c.method} ${c.url}`), ['GET /api/story-chat/conversations/conv-9', 'POST /api/story-chat/conversations/conv-9/turns'])
  assert.equal(calls[0].headers['X-Personal-Code'], 'CODE-9')
  assert.equal('Content-Type' in calls[0].headers, false)
})

test('API 새 대화: 첫 답변 전에는 이어하기 정보가 없고, 대화가 만들어지면 생긴다', async () => {
  const fridge = projects.find(p => p.id === 'fridge')!
  const fetch = async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? '{}'))
    if (url === '/api/sessions') return Response.json({ personal_code: 'CODE-1' }, { status: 201 })
    if (url.endsWith('/conversations')) return Response.json({ conversation_id: 'conv-1', project: 'fridge', completed_turns: 0, total_turns: fridge.steps.length, finished: false }, { status: 201 })
    return Response.json({ conversation_id: 'conv-1', project: 'fridge', request_id: body.request_id, turn: body.turn, replies: [{ speaker: '냉장고 회장', text: '응답' }], reaction: 'x', completed_turns: body.turn + 1, provider: 'gemini', model: 'm', latency_ms: 1, finished: false })
  }
  const client = createApiStoryClient({ displayName: '민트', fetch })
  assert.equal(client.session?.(), null)
  assert.equal(await client.progress?.(new AbortController().signal), null)
  await client.sendTurn({ requestId: 'req-new-1', project: fridge, turn: 0, input: { text: '안녕하세요' } }, new AbortController().signal)
  assert.deepEqual(client.session?.(), { code: 'CODE-1', conversationId: 'conv-1' })
})
