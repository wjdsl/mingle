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
}
export class AdminApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
// Same-origin /api, Vite proxies local development requests to the existing backend.
// Credentials remain in memory; never persist bearer tokens in localStorage.
export function createAdminClient(fetcher: typeof fetch = fetch) {
  async function request<T>(path: string, token: string | undefined, signal: AbortSignal, body?: unknown): Promise<T> {
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
    return response.json() as Promise<T>
  }
  return {
    login: (email: string, password: string, signal: AbortSignal) => request<AdminSession>('/login', undefined, signal, { email, password }),
    me: (token: string, signal: AbortSignal) => request<Admin>('/me', token, signal),
    projects: (token: string, signal: AbortSignal) => request<string[]>('/projects', token, signal),
    projectStats: (token: string, project: string, days: number, signal: AbortSignal) =>
      request<ProjectStats>(`/projects/${encodeURIComponent(project)}/stats?${new URLSearchParams({ days: String(days) })}`, token, signal),
    overview: (token: string, days: number, signal: AbortSignal, project?: string) => {
      const query = new URLSearchParams({ days: String(days) })
      if (project) query.set('project', project)
      return request<Overview>(`/overview?${query}`, token, signal)
    },
  }
}
export const adminClient = createAdminClient()
