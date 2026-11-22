export interface Admin { id: string; email: string; name: string; role: string; projects?: string[] }
export interface AdminSession { access_token: string; expires_in: number; admin: Admin }
export interface Overview {
  environment?: string
  generated_at: string; range_days: number
  totals: { sessions: number; conversations: number; completed_conversations: number; messages: number; avg_latency_ms: number; trigger_impressions: number; trigger_clicks: number; ctr: number }
  personas: { persona_id: string; slug: string; name: string; conversations: number; completed: number; messages: number; avg_turns: number }[]
  daily: { date: string; sessions: number; conversations: number; messages: number }[]
  stages: Record<string, number>
  triggers: { trigger_id: string; name: string; persona_name: string; impressions: number; clicks: number; ctr: number }[]
  recent_conversations: { conversation_id: string; persona_name: string; stage: string; turn_count: number; status: string; last_message_at: string | null }[]
}
export interface ProjectStats {
  project: string; range_days: number; generated_at: string
  chat: { sessions: number; conversations: number; completed_conversations: number; completion_rate: number | null; turns: number; avg_turns: number | null; messages: number }
  share: { share_clicks: number; image_save_clicks: number; link_opens: number; link_start_sessions: number }
  daily: { date: string; conversations: number; turns: number }[]
  scope: { mode: DataMode; real_conversations: number; sample_conversations: number; unclassified_conversations: number }
  segments: { scene_set: string; conversations: number; legacy_conversations: number; segments: { id: string; title: string; start_turn: number; reached: number; rate: number | null }[] } | null
  endings: { judged: number; unjudged_completed: number; endings: { id: string; count: number; rate: number | null }[] }
  dwell: { conversations: number; median_seconds: number | null; p90_seconds: number | null }
  interest: { applicable: boolean; free_inputs: number; unclassified: number; topics: { id: string; label: string; count: number; rate: number | null }[] }
  fallback: { llm_turns: number; fallback_turns: number; rate: number | null; reasons: { code: string; count: number }[] }
  events_scope: { real_sessions: number; sample_sessions: number }
  access: { sessions: number }
  promo: { applicable: boolean; impressions: number; clicks: number; click_sessions: number; ctr: number | null; contents: { id: string; label: string; impressions: number; clicks: number; click_sessions: number; ctr: number | null }[] }
  revisit: { revisit_sessions: number; completed_sessions: number; rate: number | null; visitors: number }
}
// real: 샘플(서버 Mock) 대화 제외, sample: 샘플만, all: 둘 다. 서버가 대화 단위로 판정한다.
export type DataMode = 'real' | 'sample' | 'all'
export class AdminApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
// Same-origin /api, Vite proxies local development requests to the existing backend.
// Credentials remain in memory; never persist bearer tokens in localStorage.
export function createAdminClient(fetcher: typeof fetch = fetch) {
  async function send(path: string, token: string | undefined, signal: AbortSignal, body?: unknown): Promise<Response> {
    let response: Response
    try {
      response = await fetcher(`/api/admin${path}`, { method: body ? 'POST' : 'GET', signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
        headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}) })
    } catch (error) {
      if (signal.aborted) throw error
      throw new AdminApiError(0, '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.')
    }
    if (!response.ok) {
      throw new AdminApiError(response.status, response.status === 401 ? (body ? '아이디 또는 비밀번호를 확인해 주세요.' : '로그인이 만료되었습니다. 다시 로그인해 주세요.') : response.status === 403 ? '관리자 접근 권한이 없습니다. 계정 설정을 확인해 주세요.' : response.status === 503 ? '서버의 관리자 인증 설정이 필요합니다. 운영 담당자에게 문의해 주세요.' : '데이터를 불러오지 못했습니다. 다시 시도해 주세요.')
    }
    return response
  }
  async function request<T>(path: string, token: string | undefined, signal: AbortSignal, body?: unknown): Promise<T> {
    return (await send(path, token, signal, body)).json() as Promise<T>
  }
  return {
    login: (email: string, password: string, signal: AbortSignal) => request<AdminSession>('/login', undefined, signal, { email, password }),
    me: (token: string, signal: AbortSignal) => request<Admin>('/me', token, signal),
    projects: (token: string, signal: AbortSignal) => request<string[]>('/projects', token, signal),
    projectStats: (token: string, project: string, days: number, signal: AbortSignal, data?: DataMode) =>
      request<ProjectStats>(`/projects/${encodeURIComponent(project)}/stats?${new URLSearchParams({ days: String(days), ...(data ? { data } : {}) })}`, token, signal),
    // CSV(FR-74): 인증 헤더가 필요해 링크 대신 내려받은 뒤 브라우저에서 파일로 저장한다.
    async statsCsv(token: string, project: string, days: number, data: DataMode, signal: AbortSignal): Promise<{ blob: Blob; filename: string }> {
      const response = await send(`/projects/${encodeURIComponent(project)}/stats.csv?${new URLSearchParams({ days: String(days), data })}`, token, signal)
      const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? `mingle-${project}-${days}d-${data}.csv`
      return { blob: await response.blob(), filename }
    },
    overview: (token: string, days: number, signal: AbortSignal, project?: string) => {
      const query = new URLSearchParams({ days: String(days) })
      if (project) query.set('project', project)
      return request<Overview>(`/overview?${query}`, token, signal)
    },
  }
}
export const adminClient = createAdminClient()
