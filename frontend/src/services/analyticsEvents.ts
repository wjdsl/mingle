// 대시보드 통계 이벤트(/api/events/track): 작품 시작 화면 진입, 체험 시작·완료, 홍보 노출·클릭.
// - 보내는 값: 탭 단위 익명 세션 ID(공유 이벤트와 같은 값), 작품 ID, 이벤트 종류, 홍보 콘텐츠 ID.
//   체험 시작·완료에만 브라우저에 오래 남는 익명 방문자 ID를 함께 보낸다(재방문율).
// - 두 ID 모두 무작위 값이다. 호칭·대화·결과·기기 정보와 연결하지 않고, 진행 저장(mingle.progress.v1.*)에도 넣지 않는다.
// - 서버에 연결한 모드(API·서버 Mock)에서만 보낸다. 브라우저 전용 Mock은 어떤 요청도 보내지 않는다.
// - 전송 실패는 사용자 흐름(링크 이동 포함)에 영향을 주지 않는다.
import { newRequestId } from './requestId.ts'
import { serverConnected, shareEvents } from './shareEvents.ts'

export type TrackEvent = 'entry_view' | 'story_start' | 'story_complete' | 'promo_impression' | 'promo_click'
type VisitorStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

// 방문자 ID 보관 위치. 초기화: 이 키를 지우거나 브라우저의 사이트 데이터를 삭제한다(forgetVisitor).
export const VISITOR_KEY = 'mingle.visitor.v1'
const ID_PATTERN = /^[A-Za-z0-9-]{8,64}$/

export function createAnalyticsEvents(options: {
  fetcher?: typeof fetch
  enabled?: (projectId: string) => boolean
  sessionId?: () => string
  storage?: () => VisitorStorage | undefined
  newId?: () => string
} = {}) {
  const fetcher = options.fetcher ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init))
  const enabled = options.enabled ?? serverConnected
  const sessionId = options.sessionId ?? (() => shareEvents.anonId())
  const newId = options.newId ?? newRequestId
  const getStorage = options.storage ?? (() => { try { return window.localStorage } catch { return undefined } })
  let memoryVisitor: string | undefined
  const sent = new Set<string>()

  // 저장소를 쓸 수 없으면(비공개 모드 등) 이 탭 메모리에만 두며, 그 경우 재방문으로 잡히지 않는다.
  function visitorId(): string {
    if (memoryVisitor) return memoryVisitor
    try {
      const stored = getStorage()?.getItem(VISITOR_KEY)
      if (stored && ID_PATTERN.test(stored)) return (memoryVisitor = stored)
    } catch { /* 저장소 접근 불가 */ }
    memoryVisitor = newId()
    try { getStorage()?.setItem(VISITOR_KEY, memoryVisitor) } catch { /* 저장소 접근 불가 */ }
    return memoryVisitor
  }

  function send(projectId: string, eventType: TrackEvent, extra: { content_id?: string; visitor_id?: string } = {}): void {
    if (!enabled(projectId)) return
    try {
      void fetcher('/api/events/track', {
        method: 'POST', keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId(), project: projectId, event_type: eventType, ...extra }),
      }).catch(() => undefined)
    } catch { /* 통계 실패는 무시 */ }
  }

  // 탭 안에서 한 번만 보내는 이벤트(서버도 같은 세션의 중복을 다시 거른다).
  function once(key: string, run: () => void) { if (!sent.has(key)) { sent.add(key); run() } }

  return {
    visitorId,
    entry: (projectId: string) => once(`entry:${projectId}`, () => send(projectId, 'entry_view')),
    start: (projectId: string) => { if (enabled(projectId)) send(projectId, 'story_start', { visitor_id: visitorId() }) },
    complete: (projectId: string) => { if (enabled(projectId)) send(projectId, 'story_complete', { visitor_id: visitorId() }) },
    promoImpression: (projectId: string, contentId: string) =>
      once(`promo:${projectId}:${contentId}`, () => send(projectId, 'promo_impression', { content_id: contentId })),
    promoClick: (projectId: string, contentId: string) => send(projectId, 'promo_click', { content_id: contentId }),
    forgetVisitor() { memoryVisitor = undefined; try { getStorage()?.removeItem(VISITOR_KEY) } catch { /* 저장소 접근 불가 */ } },
  }
}

export const analyticsEvents = createAnalyticsEvents()
