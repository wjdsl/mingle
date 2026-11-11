import test from 'node:test'
import assert from 'node:assert/strict'
import { createAdminClient, AdminApiError } from '../src/services/adminClient.ts'

test('관리자 요청은 서버 인증과 선택 기간을 전달하고 자격 증명을 URL에 넣지 않는다', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  const client = createAdminClient((async (url, init) => {
    calls.push({ url: String(url), init }); return Response.json({})
  }) as typeof fetch)
  const signal = new AbortController().signal
  await client.login('admin@example.test', 'test-only-password', signal)
  await client.me('test-only-token', signal)
  await client.overview('test-only-token', 30, signal)
  assert.equal(calls[0].url, '/api/admin/login')
  assert.equal(calls[0].init?.method, 'POST')
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { email: 'admin@example.test', password: 'test-only-password' })
  assert.equal(calls[2].url, '/api/admin/overview?days=30')
  assert.equal((calls[2].init?.headers as Record<string, string>).Authorization, 'Bearer test-only-token')
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
