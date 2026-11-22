import test from 'node:test'
import assert from 'node:assert/strict'
import { createShareEvents } from '../src/services/shareEvents.ts'

function setup(enabled = true) {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  const store = new Map<string, string>()
  const events = createShareEvents({
    fetcher: (async (url, init) => { calls.push({ url: String(url), body: JSON.parse(String(init?.body)) }); return new Response(null, { status: 204 }) }) as typeof fetch,
    storage: () => ({ getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v) } }),
    enabled: () => enabled,
    newId: () => 'anon-0000-1111',
  })
  return { events, calls }
}

test('이벤트는 익명 세션 ID·작품·종류만 보낸다', () => {
  const { events, calls } = setup()
  events.record('cloud', 'share_click')
  events.record('cloud', 'image_save_click')
  assert.equal(calls.length, 2)
  assert.equal(calls[0].url, '/api/events/share')
  assert.deepEqual(calls[0].body, { anon_id: 'anon-0000-1111', project: 'cloud', event: 'share_click' })
  assert.deepEqual(Object.keys(calls[1].body).sort(), ['anon_id', 'event', 'project'])
})

test('브라우저 전용 Mock(서버 미연결)에서는 요청을 보내지 않는다', () => {
  const { events, calls } = setup(false)
  events.record('fridge', 'share_click')
  events.captureShareEntry({ search: '?from=share', hash: '#/project/fridge' })
  events.recordStart('fridge')
  assert.equal(calls.length, 0)
})

test('공유 링크로 열린 경우에만 열기·시작을 기록하고 일반 방문은 기록하지 않는다', () => {
  const { events, calls } = setup()
  let replaced = ''
  assert.equal(events.captureShareEntry({ search: '', hash: '#/project/cloud' }), null)
  events.recordStart('cloud')
  assert.equal(calls.length, 0)
  assert.equal(events.captureShareEntry({ search: '?from=share', hash: '#/project/cloud' }, url => { replaced = url }), 'cloud')
  assert.equal(replaced, '#/project/cloud') // 공유 표시는 주소에서 제거
  events.captureShareEntry({ search: '?from=share', hash: '#/project/cloud' }) // 같은 세션의 재열기는 한 번
  events.recordStart('cloud')
  events.recordStart('fridge') // 공유로 들어오지 않은 다른 작품
  assert.deepEqual(calls.map(c => [c.body.project, c.body.event]), [['cloud', 'link_open'], ['cloud', 'link_start']])
})

test('알 수 없는 작품이나 공유 표시가 없는 주소는 무시한다', () => {
  const { events, calls } = setup()
  assert.equal(events.captureShareEntry({ search: '?from=share', hash: '#/project/unknown' }), null)
  assert.equal(events.captureShareEntry({ search: '?from=share', hash: '#/' }), null)
  assert.equal(calls.length, 0)
})

test('전송 실패는 예외를 던지지 않는다', async () => {
  const events = createShareEvents({ fetcher: (async () => { throw new TypeError('offline') }) as typeof fetch, enabled: () => true, storage: () => undefined })
  assert.doesNotThrow(() => events.record('puruma', 'share_click'))
  await new Promise(resolve => setTimeout(resolve, 0))
})
