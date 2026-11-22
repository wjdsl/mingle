import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { adminClient, AdminApiError } from '../../services/adminClient'
import type { Admin, AdminSession, ProjectStats } from '../../services/adminClient'
import { projects } from '../../projects/stories/catalog'
import './admin.css'

const number = (value: number) => value.toLocaleString('ko-KR')
const percent = (part: number, total: number) => total ? `${(part / total * 100).toFixed(1)}%` : '—'
export function AdminApp() {
  const [session, setSession] = useState<AdminSession | null>(null)
  const [admin, setAdmin] = useState<Admin | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [project, setProject] = useState('')
  const [days, setDays] = useState(14)
  const [refresh, setRefresh] = useState(0)
  const [data, setData] = useState<ProjectStats | null>(null)
  const loginRequest = useRef<AbortController | null>(null)
  const loggingIn = useRef(false)
  useEffect(() => () => loginRequest.current?.abort(), [])
  function logout(message = '') {
    setSession(null); setAdmin(null); setData(null); setPassword(''); setError(message); setBusy(false)
  }
  async function login(event: FormEvent) {
    event.preventDefault()
    if (loggingIn.current) return
    loggingIn.current = true; setBusy(true); setError('')
    const controller = new AbortController(); loginRequest.current = controller
    try {
      const next = await adminClient.login(email.trim(), password, controller.signal)
      const identity = await adminClient.me(next.access_token, controller.signal)
      if (!['admin', 'project'].includes(identity.role)) throw new AdminApiError(403, '관리자 접근 권한이 없습니다.')
      setPassword(''); setAdmin(identity); setProject(''); setSession(next)
      window.history.replaceState(null, '', '#/admin')
    } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : '로그인에 실패했습니다.') }
    finally { loggingIn.current = false; if (!controller.signal.aborted) setBusy(false) }
  }
  const allowed = projects.filter(item => admin?.projects?.includes(item.id))
  useEffect(() => {
    if (admin && allowed.length && !allowed.some(item => item.id === project)) setProject(allowed[0].id)
  }, [admin, project])
  useEffect(() => {
    if (!session || !project) return
    const controller = new AbortController()
    setBusy(true); setError(''); setData(null)
    adminClient.projectStats(session.access_token, project, days, controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result)
    }).catch(err => {
      if (controller.signal.aborted) return
      if (err instanceof AdminApiError && err.status === 401) logout(err.message)
      else setError(err instanceof AdminApiError && err.status === 403 ? '이 작품의 통계를 볼 권한이 없습니다.' : err instanceof Error ? err.message : '조회에 실패했습니다.')
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [session, project, days, refresh])
  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(() => logout('로그인이 만료되었습니다. 다시 로그인해 주세요.'), session.expires_in * 1000)
    return () => window.clearTimeout(timer)
  }, [session])
  const chat = data?.chat, share = data?.share
  const peak = data ? Math.max(1, ...data.daily.map(d => d.conversations)) : 1
  return <div className="a-app">
    <header className="a-header"><a href="#/" className="a-brand">mingle<span> / ADMIN</span></a>{admin && <div><span>{admin.name}</span><button onClick={() => logout()}>로그아웃</button></div>}</header>
    {!session ? <main className="a-login"><p className="a-eyebrow">MINGLE WORKSPACE</p><h1>관리자 로그인</h1><p>발급받은 계정으로 로그인해 주세요.</p>
      <form onSubmit={login}><label htmlFor="admin-email">이메일</label><input id="admin-email" type="email" autoComplete="username" required maxLength={200} value={email} onChange={e => setEmail(e.target.value)} disabled={busy} />
        <label htmlFor="admin-password">비밀번호</label><input id="admin-password" type="password" autoComplete="current-password" required maxLength={200} value={password} onChange={e => setPassword(e.target.value)} disabled={busy} />
        {error && <p role="alert" className="a-error">{error}</p>}<button className="a-primary" disabled={busy}>{busy ? '확인 중…' : '로그인'}</button></form><a href="#/">서비스로 돌아가기</a>
    </main> : <main className="a-main">
      <div className="a-title">
        <div><h1>이야기 운영 현황</h1><p>작품별 채팅·공유 현황을 확인해 주세요.</p></div>
        <div className="a-tools">
          <label htmlFor="admin-project">작품</label>
          <select id="admin-project" value={project} onChange={e => { setData(null); setProject(e.target.value) }} disabled={!allowed.length}>
            {allowed.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
          <label htmlFor="admin-days">조회 기간</label>
          <select id="admin-days" value={days} onChange={e => setDays(Number(e.target.value))}>
            {[7, 14, 30, 90].map(n => <option value={n} key={n}>최근 {n}일</option>)}
          </select>
          <button onClick={() => setRefresh(n => n + 1)} disabled={busy || !project}>새로고침</button>
        </div>
      </div>
      <p className="a-notice">서버에 저장된 채팅과 공유 이벤트를 집계해요. 브라우저에서만 동작하는 Mock 체험은 기록되지 않고, 서버 Mock 체험은 기록돼요.</p>
      {!allowed.length && <p className="a-empty">조회할 수 있는 작품이 배정되지 않았어요. 운영 담당자에게 문의해 주세요.</p>}
      {busy && <p role="status" className="a-loading">통계를 불러오는 중…</p>}{error && <div role="alert" className="a-error">{error} <button onClick={() => setRefresh(n => n + 1)}>다시 시도</button></div>}
      {data && chat && share && <>
        <p className="a-updated">KST 오늘 포함 {data.range_days}일 · {new Date(data.generated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} 갱신</p>
        <section className="a-kpis" aria-label="채팅 지표">{[
          ['채팅 이용 세션', number(chat.sessions), '기간 내 대화를 시작한 세션'],
          ['시작한 대화', number(chat.conversations), '기간 내 생성된 대화'],
          ['완료율', chat.completion_rate === null ? '—' : `${chat.completion_rate}%`, `대화 ${number(chat.completed_conversations)}건 완료 · 현재 상태`],
          ['진행 턴', number(chat.turns), chat.avg_turns === null ? '저장된 응답 턴 합계' : `대화당 평균 ${chat.avg_turns}턴`],
        ].map(([label, value, help]) => <article className="a-kpi" key={label}><h2>{label}</h2><strong>{value}</strong><p>{help}</p></article>)}</section>
        {!chat.conversations && <p className="a-empty">선택한 기간에 시작된 대화가 없습니다. 데이터가 수집되면 통계가 표시됩니다.</p>}
        <section className="a-kpis" aria-label="공유 지표">{[
          ['링크 공유 버튼', number(share.share_clicks), '결과 화면에서 버튼을 누른 횟수'],
          ['이미지 저장 버튼', number(share.image_save_clicks), '결과 화면에서 버튼을 누른 횟수'],
          ['공유 링크 열기', number(share.link_opens), '공유 링크로 열린 세션 수'],
          ['링크로 체험 시작', number(share.link_start_sessions), `공유 링크 열기 대비 ${percent(share.link_start_sessions, share.link_opens)}`],
        ].map(([label, value, help]) => <article className="a-kpi" key={label}><h2>{label}</h2><strong>{value}</strong><p>{help}</p></article>)}</section>
        <p className="a-notice">공유 버튼은 누른 횟수이며 외부에 실제로 올렸는지는 알 수 없어요.</p>
        <section className="a-panel"><h2>일별 대화 시작</h2><p>한국 시간 기준 · 막대를 선택하면 수치를 확인할 수 있습니다.</p><div className="a-chart" aria-label="일별 대화 수">{data.daily.map(point => <div className="a-chart-column" key={point.date}><div className="a-chart-track"><button aria-label={`${point.date}: 대화 ${point.conversations}건`} title={`${point.date}: ${point.conversations}건`} style={{ height: `${Math.max(3, point.conversations / peak * 100)}%` }} onClick={e => e.currentTarget.focus()}><span>{point.conversations}</span></button></div><small>{point.date.slice(5)}</small></div>)}</div><details><summary>일별 수치 표로 보기</summary><div className="a-table-scroll"><table><thead><tr><th>날짜</th><th>시작한 대화</th><th>진행 턴</th></tr></thead><tbody>{data.daily.map(p => <tr key={p.date}><th>{p.date}</th><td>{p.conversations}</td><td>{p.turns}</td></tr>)}</tbody></table></div></details></section>
      </>}
    </main>}
  </div>
}
