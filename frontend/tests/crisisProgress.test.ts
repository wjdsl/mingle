import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { saveProgress, loadProgress } from '../src/services/storyProgress.ts'
import { withSourceTrace } from '../src/services/storyClient.ts'

// 위기 입력은 진행 저장·완료 턴에 반영하지 않는다(#18 진행 저장 ↔ #17 위기 안내 통합 회귀).
function memoryStorage() {
  const data = new Map<string, string>()
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) } }
}

test('저장된 진행에는 대화·입력 원문 필드가 없다', () => {
  const storage = memoryStorage()
  saveProgress({ project: 'fridge', mode: 'scenario-mock', name: '입주민', completedTurns: 2 }, storage)
  const raw = storage.data.get('mingle.progress.v1.fridge')!
  assert.deepEqual(Object.keys(JSON.parse(raw)).sort(), ['completedTurns', 'mode', 'name', 'project', 'savedAt', 'v'])
  assert.equal(loadProgress('fridge', 'scenario-mock', storage)?.completedTurns, 2)
})

test('useStoryChat: 위기 분기(프론트·서버 safety)는 진행 저장을 호출하지 않고 장면을 진행하지 않는다', () => {
  const source = readFileSync(new URL('../src/features/platform/useStoryChat.ts', import.meta.url), 'utf8')
  const front = source.slice(source.indexOf('if (choice === undefined && step.inputMode'), source.indexOf('pending.current = { requestId: newRequestId()'))
  assert.match(front, /isCrisisText\(text\)/)
  assert.doesNotMatch(front, /remember\(|saveProgress|setStatus\(|setTurn\(|onResult/)
  const server = source.slice(source.indexOf('reply.safety'), source.indexOf('} else if (!abort.signal.aborted)'))
  assert.match(server, /safetyMessages\(/)
  assert.doesNotMatch(server, /remember\(|saveProgress|setTurn\(|onResult|setStatus\('replied'\)/)
  // 정상 응답 뒤에만 진행이 저장된다.
  assert.match(source, /setStatus\('replied'\)\s*\n\s*remember\(turn \+ 1\)/)
})

test('출처 추적 래퍼는 진행 복원용 session()·progress()를 잃지 않는다 (#17 ↔ #18 통합 회귀)', async () => {
  const inner = {
    sendTurn: async () => ({ speaker: 'a', text: 't', reaction: 'r' }),
    session: () => ({ code: 'c', conversationId: 'x' }),
    progress: async () => ({ completedTurns: 1, totalTurns: 10, finished: false }),
  }
  const wrapped = withSourceTrace(inner as never, 'api') as unknown as typeof inner
  assert.deepEqual(wrapped.session(), { code: 'c', conversationId: 'x' })
  assert.equal((await wrapped.progress()).completedTurns, 1)
})
