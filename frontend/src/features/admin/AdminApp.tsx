import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { adminClient, AdminApiError } from '../../services/adminClient'
import type { Admin, AdminSession, Overview } from '../../services/adminClient'
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
  const [days, setDays] = useState(14)
  const [refresh, setRefresh] = useState(0)
  const [data, setData] = useState<Overview | null>(null)
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
      if (identity.role !== 'admin') throw new AdminApiError(403, '관리자 접근 권한이 없습니다.')
      setPassword(''); setAdmin(identity); setSession(next)
      window.history.replaceState(null, '', '#/admin')
    } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : '로그인에 실패했습니다.') }
    finally { loggingIn.current = false; if (!controller.signal.aborted) setBusy(false) }
  }
  useEffect(() => {
    if (!session) return
    const controller = new AbortController()
    setBusy(true); setError(''); setData(null)
    adminClient.overview(session.access_token, days, controller.signal).then(setData).catch(err => {
      if (controller.signal.aborted) return
      if (err instanceof AdminApiError && [401, 403].includes(err.status)) logout(err.message)
      else setError(err instanceof Error ? err.message : '조회에 실패했습니다.')
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [session, days, refresh])
  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(() => logout('로그인이 만료되었습니다. 다시 로그인해 주세요.'), session.expires_in * 1000)
    return () => window.clearTimeout(timer)
  }, [session])
  return <div className="a-app">
    <header className="a-header"><a href="#/" className="a-brand">mingle<span> / ADMIN</span></a>{admin && <div><span>{admin.name}</span><button onClick={() => logout()}>로그아웃</button></div>}</header>
    {!session ? <main className="a-login"><p className="a-eyebrow">MINGLE WORKSPACE</p><h1>관리자 로그인</h1><p>발급받은 계정으로 로그인해 주세요.</p>
      <form onSubmit={login}><label htmlFor="admin-email">이메일</label><input id="admin-email" type="email" autoComplete="username" required maxLength={200} value={email} onChange={e => setEmail(e.target.value)} disabled={busy} />
        <label htmlFor="admin-password">비밀번호</label><input id="admin-password" type="password" autoComplete="current-password" required maxLength={200} value={password} onChange={e => setPassword(e.target.value)} disabled={busy} />
        {error && <p role="alert" className="a-error">{error}</p>}<button className="a-primary" disabled={busy}>{busy ? '확인 중…' : '로그인'}</button></form><a href="#/">서비스로 돌아가기</a>
    </main> : <main className="a-main">
      <div className="a-title"><div><p className="a-eyebrow">ALL CONTENTS · SERVER DATA</p><h1>이야기 운영 현황</h1><p>서버에 등록된 전체 캐릭터의 이용 데이터를 확인하세요.</p></div><div className="a-tools"><label htmlFor="admin-days">조회 기간</label><select id="admin-days" value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 14, 30, 90].map(n => <option value={n} key={n}>최근 {n}일</option>)}</select><button onClick={() => setRefresh(n => n + 1)} disabled={busy}>새로고침</button></div></div>
      <aside className="a-notice"><strong>프론트엔드 3개 작품 통계는 아직 연결되지 않았습니다.</strong><span>푸르마·냉장고·구름섬의 Mock 채팅은 서버에 전송되지 않습니다. 아래는 서버 DB의 실제 집계이며, 테스트 서버에는 테스트 데이터가 포함될 수 있습니다.</span></aside>
      {busy && <p role="status" className="a-loading">통계를 불러오는 중…</p>}{error && <div role="alert" className="a-error">{error} <button onClick={() => setRefresh(n => n + 1)}>다시 시도</button></div>}
      {data && <>
        {data.environment === 'local-qa' && <p className="a-notice"><strong>로컬 검증 데이터</strong>분리된 테스트 DB의 데이터입니다. 실제 서비스 이용 통계가 아닙니다.</p>}
        <p className="a-updated">KST 오늘 포함 {data.range_days}일 · {new Date(data.generated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} 갱신</p>
        <section className="a-kpis" aria-label="핵심 지표">{[
          ['신규 세션', number(data.totals.sessions), '기간 내 생성된 사용자 세션'],
          ['시작한 대화', number(data.totals.conversations), '기간 내 생성된 대화'],
          ['완료율', percent(data.totals.completed_conversations, data.totals.conversations), `대화 ${number(data.totals.completed_conversations)}건 완료 · 현재 상태`],
          ['주고받은 메시지', number(data.totals.messages), '기간 내 사용자·캐릭터 메시지'],
        ].map(([label, value, help]) => <article className="a-kpi" key={label}><h2>{label}</h2><strong>{value}</strong><p>{help}</p></article>)}</section>
        {!data.totals.conversations && <p className="a-empty">선택한 기간에 시작된 대화가 없습니다. 데이터가 수집되면 통계가 표시됩니다.</p>}
        <div className="a-grid"><section className="a-panel"><h2>일별 대화 시작</h2><p>한국 시간 기준 · 막대를 선택하면 수치를 확인할 수 있습니다.</p><div className="a-chart" aria-label="일별 대화 수">{data.daily.map(point => <div className="a-chart-column" key={point.date}><div className="a-chart-track"><button aria-label={`${point.date}: 대화 ${point.conversations}건`} title={`${point.date}: ${point.conversations}건`} style={{ height: `${Math.max(3, point.conversations / Math.max(1, ...data.daily.map(d => d.conversations)) * 100)}%` }} onClick={e => e.currentTarget.focus()}><span>{point.conversations}</span></button></div><small>{point.date.slice(5)}</small></div>)}</div><details><summary>일별 수치 표로 보기</summary><div className="a-table-scroll"><table><thead><tr><th>날짜</th><th>신규 세션</th><th>대화</th><th>메시지</th></tr></thead><tbody>{data.daily.map(p => <tr key={p.date}><th>{p.date}</th><td>{p.sessions}</td><td>{p.conversations}</td><td>{p.messages}</td></tr>)}</tbody></table></div></details></section>
          <section className="a-panel"><h2>관계 단계 분포</h2><p>기간 내 시작한 대화의 현재 관계 단계입니다. 장면 도달률과는 다른 지표입니다.</p>{Object.entries(data.stages).length ? Object.entries(data.stages).map(([stage, count]) => <div className="a-stage" key={stage}><span>{stage}</span><meter min={0} max={Math.max(1, data.totals.conversations)} value={count} /><strong>{count}건</strong></div>) : <p className="a-empty">아직 관계 단계 데이터가 없습니다.</p>}<hr /><p>평균 응답 시간 <strong>{number(data.totals.avg_latency_ms)} ms</strong></p><p>홍보 클릭 <strong>{number(data.totals.trigger_clicks)}회</strong> · 클릭률 <strong>{data.totals.ctr}%</strong></p></section></div>
        <section className="a-panel"><h2>서버 캐릭터별 이용 현황</h2><div className="a-table-scroll"><table><thead><tr><th>캐릭터</th><th>시작한 대화</th><th>완료</th><th>완료율</th><th>메시지</th><th>평균 턴</th></tr></thead><tbody>{data.personas.map(p => <tr key={p.persona_id}><th>{p.name}<small>{p.slug}</small></th><td>{number(p.conversations)}</td><td>{number(p.completed)}</td><td>{percent(p.completed, p.conversations)}</td><td>{number(p.messages)}</td><td>{p.avg_turns}</td></tr>)}</tbody></table></div></section>
        <section className="a-panel"><h2>홍보 콘텐츠 반응</h2><div className="a-table-scroll"><table><thead><tr><th>콘텐츠</th><th>캐릭터</th><th>노출</th><th>클릭</th><th>클릭률</th></tr></thead><tbody>{data.triggers.map(t => <tr key={t.trigger_id}><th>{t.name}</th><td>{t.persona_name}</td><td>{t.impressions}</td><td>{t.clicks}</td><td>{t.ctr}%</td></tr>)}</tbody></table></div>{!data.triggers.length && <p className="a-empty">등록된 홍보 콘텐츠가 없습니다.</p>}</section>
        <section className="a-panel"><h2>최근 대화 현황</h2><p>채팅 원문과 사용자 이름을 표시하지 않습니다.</p><div className="a-table-scroll"><table><thead><tr><th>캐릭터</th><th>단계</th><th>턴</th><th>상태</th><th>최근 활동</th></tr></thead><tbody>{data.recent_conversations.map(c => <tr key={c.conversation_id}><th>{c.persona_name}</th><td>{c.stage}</td><td>{c.turn_count}</td><td><span className="a-status">{c.status === 'completed' ? '완료' : c.status === 'active' ? '진행 중' : c.status}</span></td><td>{c.last_message_at ? new Date(c.last_message_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '활동 없음'}</td></tr>)}</tbody></table></div>{!data.recent_conversations.length && <p className="a-empty">최근 대화가 없습니다.</p>}</section>
      </>}
    </main>}
  </div>
}
