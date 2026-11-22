// 공유 통계 이벤트. 익명 세션 ID·작품 ID·이벤트 종류만 서버(/api/events/share)로 보낸다.
// 호칭, 대화, 결과 내용은 보내지 않는다. 서버에 연결한 모드(API)에서만 보내고,
// 브라우저 전용 Mock 모드에서는 어떤 요청도 보내지 않는다. 전송 실패는 사용자 흐름에 영향을 주지 않는다.
import { newRequestId } from './requestId.ts'
import { storyClientMode } from './storyClient.ts'
import { purumaStoryMode } from './apiPurumaStoryClient.ts'

export type ShareEventKind = 'share_click' | 'image_save_click' | 'link_open' | 'link_start'
export type ShareStorage = Pick<Storage, 'getItem' | 'setItem'>

const ANON_KEY = 'mingle.anon-session'
const SHARE_PARAM = 'from'
const SHARE_VALUE = 'share'

export function serverConnected(projectId: string): boolean {
  // scenario-mock은 서버 Mock(백엔드 LLM_PROVIDER=mock)에 연결하는 모드라 서버에 기록이 남는다. 'mock'만 브라우저 전용이다.
  return projectId === 'puruma' ? purumaStoryMode() !== 'mock' : storyClientMode() !== 'mock'
}

export function createShareEvents(options: {
  fetcher?: typeof fetch
  storage?: () => ShareStorage | undefined
  enabled?: (projectId: string) => boolean
  newId?: () => string
} = {}) {
  const fetcher = options.fetcher ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init))
  const enabled = options.enabled ?? serverConnected
  const newId = options.newId ?? newRequestId
  const getStorage = options.storage ?? (() => { try { return window.sessionStorage } catch { return undefined } })
  let memoryId: string | undefined
  const sharedEntries = new Set<string>()

  // 브라우저 탭(세션) 단위 익명 ID. 저장소를 쓸 수 없으면 메모리에만 둔다.
  function anonId(): string {
    if (memoryId) return memoryId
    try {
      const stored = getStorage()?.getItem(ANON_KEY)
      if (stored && /^[A-Za-z0-9-]{8,64}$/.test(stored)) return (memoryId = stored)
    } catch { /* 저장소 접근 불가 */ }
    memoryId = newId()
    try { getStorage()?.setItem(ANON_KEY, memoryId) } catch { /* 저장소 접근 불가 */ }
    return memoryId
  }

  function record(projectId: string, event: ShareEventKind): void {
    if (!enabled(projectId)) return
    try {
      void fetcher('/api/events/share', {
        method: 'POST', keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anon_id: anonId(), project: projectId, event }),
      }).catch(() => undefined)
    } catch { /* 통계 실패는 무시 */ }
  }

  // 공유 링크(?from=share#/project/<id>)로 열렸을 때 한 번 기록하고, 주소에서 표시를 지운다.
  function captureShareEntry(location: Pick<Location, 'search' | 'hash'>, replaceUrl?: (url: string) => void): string | null {
    const params = new URLSearchParams(location.search)
    if (params.get(SHARE_PARAM) !== SHARE_VALUE) return null
    const projectId = /^#\/project\/([a-z]+)/.exec(location.hash)?.[1]
    params.delete(SHARE_PARAM)
    const query = params.toString()
    replaceUrl?.(`${query ? `?${query}` : ''}${location.hash}`)
    if (!projectId || !['puruma', 'fridge', 'cloud'].includes(projectId)) return null
    if (!sharedEntries.has(projectId)) { sharedEntries.add(projectId); record(projectId, 'link_open') }
    return projectId
  }

  return {
    record, anonId, captureShareEntry,
    enteredFromShare: (projectId: string) => sharedEntries.has(projectId),
    // 공유 링크로 들어온 세션이 체험 시작 버튼을 눌렀을 때. 일반 방문은 기록하지 않는다.
    recordStart(projectId: string) { if (sharedEntries.has(projectId)) record(projectId, 'link_start') },
  }
}

export const shareEvents = createShareEvents()
// 공유 페이지(shareCards.ts의 SHARE_QUERY)와 같은 값이어야 한다(테스트로 확인).
export const SHARE_LINK_QUERY = `${SHARE_PARAM}=${SHARE_VALUE}`
