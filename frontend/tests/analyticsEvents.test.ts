import test from 'node:test'
import assert from 'node:assert/strict'
import { createAnalyticsEvents, VISITOR_KEY } from '../src/services/analyticsEvents.ts'

function memoryStorage() {
  const data = new Map<string, string>()
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) } }
}

function setup(enabled = true) {
  const bodies: Record<string, unknown>[] = []
  const urls: string[] = []
  const storage = memoryStorage()
  let n = 0
  const events = createAnalyticsEvents({
    fetcher: (async (url, init) => { urls.push(String(url)); bodies.push(JSON.parse(String(init?.body))); return new Response(null, { status: 204 }) }) as typeof fetch,
    enabled: () => enabled,
    sessionId: () => 'tab-session-0001',
    storage: () => storage,
    newId: () => `visitor-id-${String(++n).padStart(4, '0')}`,
  })
  return { events, bodies, urls, storage }
}

test('브라우저 전용 Mock(서버 미연결)에서는 어떤 요청도 보내지 않고 방문자 ID도 만들지 않는다', () => {
  const { events, bodies, storage } = setup(false)
  events.entry('fridge'); events.start('fridge'); events.complete('fridge')
  events.promoImpression('puruma', 'rag_library_central'); events.promoClick('puruma', 'rag_library_central')
  assert.equal(bodies.length, 0)
  assert.equal(storage.data.has(VISITOR_KEY), false)
})

test('명세 필드만 보내고 방문자 ID는 시작·완료에만 붙인다', () => {
  const { events, bodies, urls } = setup()
  events.entry('cloud')
  events.start('cloud')
  events.complete('cloud')
  events.promoClick('puruma', 'rag_career_center')
  assert.ok(urls.every(u => u === '/api/events/track'))
  assert.deepEqual(bodies[0], { session_id: 'tab-session-0001', project: 'cloud', event_type: 'entry_view' })
  assert.deepEqual(bodies[1], { session_id: 'tab-session-0001', project: 'cloud', event_type: 'story_start', visitor_id: 'visitor-id-0001' })
  assert.equal(bodies[2].visitor_id, 'visitor-id-0001')
  assert.deepEqual(bodies[3], { session_id: 'tab-session-0001', project: 'puruma', event_type: 'promo_click', content_id: 'rag_career_center' })
  for (const body of bodies) assert.deepEqual(Object.keys(body).filter(k => !['session_id', 'project', 'event_type', 'visitor_id', 'content_id'].includes(k)), [])
})

test('접속·노출은 탭에서 한 번, 클릭·시작은 매번 보낸다', () => {
  const { events, bodies } = setup()
  events.entry('fridge'); events.entry('fridge'); events.entry('cloud')
  events.promoImpression('puruma', 'rag_library_central'); events.promoImpression('puruma', 'rag_library_central')
  events.promoClick('puruma', 'rag_library_central'); events.promoClick('puruma', 'rag_library_central')
  events.start('fridge'); events.start('fridge')
  const kinds = bodies.map(b => `${b.event_type}:${b.project}`)
  assert.deepEqual(kinds, ['entry_view:fridge', 'entry_view:cloud', 'promo_impression:puruma', 'promo_click:puruma', 'promo_click:puruma', 'story_start:fridge', 'story_start:fridge'])
})

test('방문자 ID는 localStorage(mingle.visitor.v1)에 남아 다음 방문에 재사용되고, 지우면 새로 만든다', () => {
  const { events, storage } = setup()
  const first = events.visitorId()
  assert.equal(storage.data.get(VISITOR_KEY), first)
  const again = createAnalyticsEvents({ storage: () => storage, enabled: () => true, fetcher: (async () => new Response(null)) as typeof fetch, sessionId: () => 'tab-session-0002' })
  assert.equal(again.visitorId(), first)
  events.forgetVisitor()
  assert.equal(storage.data.has(VISITOR_KEY), false)
  assert.notEqual(events.visitorId(), first)
})

test('전송 실패는 밖으로 던지지 않는다(링크 이동을 막지 않음)', () => {
  const events = createAnalyticsEvents({ enabled: () => true, sessionId: () => 'tab-session-0003', storage: () => undefined,
    fetcher: (() => { throw new TypeError('offline') }) as unknown as typeof fetch })
  assert.doesNotThrow(() => events.promoClick('puruma', 'rag_library_central'))
  const rejecting = createAnalyticsEvents({ enabled: () => true, sessionId: () => 'tab-session-0004', storage: () => undefined,
    fetcher: (async () => { throw new TypeError('offline') }) as typeof fetch })
  assert.doesNotThrow(() => rejecting.promoClick('puruma', 'rag_library_central'))
})
