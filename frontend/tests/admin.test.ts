import test from 'node:test'
import assert from 'node:assert/strict'
import { createAdminClient, AdminApiError } from '../src/services/adminClient.ts'
import { DATA_MODES, endingTitle, formatDuration, rateText, showsSample } from '../src/features/admin/metrics.ts'

test('관리자 요청은 서버 인증과 선택 기간을 전달하고 자격 증명을 URL에 넣지 않는다', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  const client = createAdminClient((async (url, init) => {
    calls.push({ url: String(url), init }); return Response.json({})
  }) as typeof fetch)
  const signal = new AbortController().signal
  await client.login('admin@example.test', 'test-only-password', signal)
  await client.me('test-only-token', signal)
  await client.overview('test-only-token', 30, signal)
  await client.overview('test-only-token', 14, signal, 'cloud')
  assert.equal(calls[0].url, '/api/admin/login')
  assert.equal(calls[0].init?.method, 'POST')
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { email: 'admin@example.test', password: 'test-only-password' })
  assert.equal(calls[2].url, '/api/admin/overview?days=30')
  assert.equal((calls[2].init?.headers as Record<string, string>).Authorization, 'Bearer test-only-token')
  assert.equal(calls[3].url, '/api/admin/overview?days=14&project=cloud')
  await client.projectStats('test-only-token', 'fridge', 30, signal)
  await client.projects('test-only-token', signal)
  assert.equal(calls[4].url, '/api/admin/projects/fridge/stats?days=30')
  assert.equal(calls[5].url, '/api/admin/projects')
  assert.equal((calls[4].init?.headers as Record<string, string>).Authorization, 'Bearer test-only-token')
})

test('401/403/503 및 연결 실패를 실제 성공 응답으로 바꾸지 않는다', async () => {
  for (const status of [401, 403, 503, 500]) {
    const client = createAdminClient((async () => new Response('', { status })) as typeof fetch)
    await assert.rejects(client.overview('invalid', 14, new AbortController().signal), (err: unknown) => err instanceof AdminApiError && err.status === status)
  }
  const client = createAdminClient((async () => { throw new TypeError('offline') }) as typeof fetch)
  await assert.rejects(client.me('invalid', new AbortController().signal), (err: unknown) => err instanceof AdminApiError && err.status === 0)
})

test('화면을 떠난 요청 취소는 네트워크 오류로 변환하지 않는다', async () => {
  const controller = new AbortController(); controller.abort()
  const cancelled = new DOMException('cancelled', 'AbortError')
  const client = createAdminClient((async () => { throw cancelled }) as typeof fetch)
  await assert.rejects(client.me('token', controller.signal), err => err === cancelled)
})

test('작품 통계는 데이터 선택(실제/샘플/전체)을 서버로 전달한다', async () => {
  const urls: string[] = []
  const client = createAdminClient((async url => { urls.push(String(url)); return Response.json({}) }) as typeof fetch)
  const signal = new AbortController().signal
  await client.projectStats('test-only-token', 'puruma', 14, signal, 'real')
  await client.projectStats('test-only-token', 'cloud', 7, signal, 'sample')
  await client.projectStats('test-only-token', 'fridge', 30, signal, 'all')
  assert.deepEqual(urls, [
    '/api/admin/projects/puruma/stats?days=14&data=real',
    '/api/admin/projects/cloud/stats?days=7&data=sample',
    '/api/admin/projects/fridge/stats?days=30&data=all',
  ])
})

test('대시보드 표시: 샘플 표시 여부, 체류 시간 단위, 결말 이름', () => {
  assert.equal(showsSample('real'), false)
  assert.equal(showsSample('sample'), true)
  assert.equal(showsSample('all'), true)
  assert.deepEqual(DATA_MODES.map(m => m.id), ['real', 'sample', 'all'])
  assert.equal(formatDuration(null), '—')
  assert.equal(formatDuration(45), '45초')
  assert.equal(formatDuration(270), '4분 30초')
  assert.equal(formatDuration(540), '9분')
  assert.equal(formatDuration(3720), '1시간 2분')
  assert.equal(endingTitle('fridge', 'fridge_rel_stage_3'), '동업자')
  assert.equal(endingTitle('cloud', 'cloud_result_dudu'), '묵묵한 버팀목형')
  assert.equal(endingTitle('puruma', 'cc_pruma'), 'CC 푸르마')
  assert.equal(endingTitle('cloud', 'unknown_id'), 'unknown_id')
  assert.equal(rateText(null), '—')
  assert.equal(rateText(12.5), '12.5%')
})
