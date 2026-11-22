import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { adminClient, AdminApiError } from '../../services/adminClient'
import type { Admin, AdminSession, DataMode, ProjectStats } from '../../services/adminClient'
import { DATA_MODES, endingTitle, formatDuration, rateText, showsSample } from './metrics'
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
  const [mode, setMode] = useState<DataMode>('real')
  const [csvBusy, setCsvBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [data, setData] = useState<ProjectStats | null>(null)
  const loginRequest = useRef<AbortController | null>(null)
  const loggingIn = useRef(false)
  useEffect(() => () => loginRequest.current?.abort(), [])
  function logout(message = '') {
    setSession(null); setAdmin(null); setData(null); setPassword(''); setError(message); setBusy(false); setMode('real')
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
    adminClient.projectStats(session.access_token, project, days, controller.signal, mode).then(result => {
      if (!controller.signal.aborted) setData(result)
    }).catch(err => {
      if (controller.signal.aborted) return
      if (err instanceof AdminApiError && err.status === 401) logout(err.message)
      else setError(err instanceof AdminApiError && err.status === 403 ? '이 작품의 통계를 볼 권한이 없습니다.' : err instanceof Error ? err.message : '조회에 실패했습니다.')
    }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [session, project, days, mode, refresh])
  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(() => logout('로그인이 만료되었습니다. 다시 로그인해 주세요.'), session.expires_in * 1000)
    return () => window.clearTimeout(timer)
  }, [session])
  const chat = data?.chat, share = data?.share
  const sample = showsSample(data?.scope.mode ?? mode)
  async function downloadCsv() {
    if (!session || !project || csvBusy) return
    setCsvBusy(true); setError('')
    const controller = new AbortController()
    try {
      const { blob, filename } = await adminClient.statsCsv(session.access_token, project, days, mode, controller.signal)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = filename
      document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      if (err instanceof AdminApiError && err.status === 401) logout(err.message)
      else setError(err instanceof AdminApiError && err.status === 403 ? '이 작품의 통계를 내려받을 권한이 없습니다.' : 'CSV를 내려받지 못했습니다. 다시 시도해 주세요.')
    } finally { setCsvBusy(false) }
  }
  const peak = data ? Math.max(1, ...data.daily.map(d => d.conversations)) : 1
  return <div className="a-app">
    <header className="a-header"><a href="#/" className="a-brand">mingle<span> / ADMIN</span></a>{admin && <div><span>{admin.name}</span><button onClick={() => logout()}>로그아웃</button></div>}</header>
    {!session ? <main className="a-login"><p className="a-eyebrow">MINGLE WORKSPACE</p><h1>관리자 로그인</h1><p>발급받은 계정으로 로그인해 주세요.</p>
      <form onSubmit={login}><label htmlFor="admin-email">아이디</label><input id="admin-email" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} required minLength={3} maxLength={200} value={email} onChange={e => setEmail(e.target.value)} disabled={busy} />
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
          <label htmlFor="admin-data">데이터</label>
          <select id="admin-data" value={mode} onChange={e => setMode(e.target.value as DataMode)}>
            {DATA_MODES.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}
          </select>
          <button onClick={() => setRefresh(n => n + 1)} disabled={busy || !project}>새로고침</button>
          <button onClick={downloadCsv} disabled={csvBusy || !project || !data}>{csvBusy ? '내려받는 중…' : 'CSV 내려받기'}</button>
        </div>
      </div>
      <p className="a-notice">서버에 저장된 채팅과 공유·접속·홍보 이벤트를 집계해요. 브라우저에서만 동작하는 Mock 체험은 기록되지 않고, 서버 Mock 체험은 기록돼요.</p>
      {!allowed.length && <p className="a-empty">조회할 수 있는 작품이 배정되지 않았어요. 운영 담당자에게 문의해 주세요.</p>}
      {busy && <p role="status" className="a-loading">통계를 불러오는 중…</p>}{error && <div role="alert" className="a-error">{error} <button onClick={() => setRefresh(n => n + 1)}>다시 시도</button></div>}
      {data && chat && share && <>
        <p className="a-updated">{sample && <span className="a-sample">샘플 데이터</span>}KST 오늘 포함 {data.range_days}일 · {new Date(data.generated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} 갱신</p>
        {sample ? <p className="a-notice a-notice-sample" role="note"><strong>샘플 데이터{data.scope.mode === 'all' ? '가 섞여 있어요' : '예요'}</strong><span>서버 Mock(테스트 응답)으로 만든 대화{data.scope.mode === 'all' ? '를 실제 대화와 함께 집계했어요' : '만 집계했어요'}. 실제 이용 통계로 쓰지 마세요. 이 기간 대화: 실제 {number(data.scope.real_conversations)}건 · 샘플 {number(data.scope.sample_conversations)}건{data.scope.unclassified_conversations ? ` · 판정 불가 ${number(data.scope.unclassified_conversations)}건` : ''} · 접속·홍보·재방문 이벤트 세션: 실제 {number(data.events_scope.real_sessions)} · 샘플 {number(data.events_scope.sample_sessions)}</span></p>
          : (data.scope.sample_conversations > 0 || data.scope.unclassified_conversations > 0 || data.events_scope.sample_sessions > 0) && <p className="a-notice" role="note">{data.events_scope.sample_sessions > 0 && <span>서버 Mock 상태에서 받은 접속·홍보·재방문 이벤트 세션 {number(data.events_scope.sample_sessions)}개는 제외했어요.</span>}{data.scope.sample_conversations > 0 && <span>이 기간의 샘플 데이터(서버 Mock 대화) {number(data.scope.sample_conversations)}건은 제외했어요. 위의 데이터 선택에서 따로 볼 수 있어요.</span>}{data.scope.unclassified_conversations > 0 && <span>저장된 턴이 없는 대화 {number(data.scope.unclassified_conversations)}건은 샘플 여부를 알 수 없어 실제 대화로 셌어요.</span>}</p>}
        <section className="a-kpis" aria-label="방문 지표">{[
          ['총 접속 수', number(data.access.sessions), '작품 시작 화면에 들어온 세션 · 같은 탭 재진입은 한 번'],
          ['재방문율', rateText(data.revisit.rate), `두 번째 이상 시작한 세션 ${number(data.revisit.revisit_sessions)} / 완료한 세션 ${number(data.revisit.completed_sessions)}`],
          ['시작한 방문자', number(data.revisit.visitors), '체험을 시작한 브라우저 수(익명 ID)'],
        ].map(([label, value, help]) => <article className="a-kpi" key={label}><h2>{label}</h2><strong>{value}</strong><p>{help}</p></article>)}</section>
        <p className="a-notice">재방문율은 기획서 정의(두 번째 이상 시작한 세션 ÷ 완료한 세션)대로 계산해요. 분자가 분모에 포함되지 않아 100%를 넘을 수 있어요. 같은 탭에서 다시 하기는 재방문으로 세지 않아요.</p>
        <section className="a-kpis a-kpis-5" aria-label="채팅 지표">{[
          ['채팅 이용 세션', number(chat.sessions), '기간 내 대화를 시작한 세션'],
          ['시작한 대화', number(chat.conversations), '기간 내 생성된 대화'],
          ['완료율', chat.completion_rate === null ? '—' : `${chat.completion_rate}%`, `대화 ${number(chat.completed_conversations)}건 완료 · 현재 상태`],
          ['진행 턴', number(chat.turns), chat.avg_turns === null ? '저장된 응답 턴 합계' : `대화당 평균 ${chat.avg_turns}턴`],
          ['체류 시간(근사)', formatDuration(data.dwell.median_seconds), data.dwell.conversations ? `중앙값 · p90 ${formatDuration(data.dwell.p90_seconds)} · 대화 ${number(data.dwell.conversations)}건` : '턴이 2개 이상인 대화가 없어요'],
        ].map(([label, value, help]) => <article className="a-kpi" key={label}><h2>{label}</h2><strong>{value}</strong><p>{help}</p></article>)}</section>
        <p className="a-notice">체류 시간은 서버에 저장된 첫 턴부터 마지막 턴까지의 시간으로 근사해요. 첫 장면을 읽는 시간과 마지막 턴 뒤의 시간은 들어가지 않아요.</p>
        {!chat.conversations && <p className="a-empty">선택한 기간에 시작된 대화가 없습니다. 데이터가 수집되면 통계가 표시됩니다.</p>}
        {data.segments && <section className="a-panel" aria-labelledby="admin-segments"><h2 id="admin-segments">구간 도달률</h2>
          <p>현재 장면 세트로 시작한 대화 {number(data.segments.conversations)}건 중 각 구간의 첫 장면을 받은 대화 비율이에요.{data.segments.legacy_conversations > 0 && ` 이전 장면 세트 대화 ${number(data.segments.legacy_conversations)}건은 구간 정의가 달라 뺐어요.`}</p>
          {data.segments.conversations ? <>
            {data.segments.segments.map(seg => <div className="a-stage" key={seg.id}><span className="a-stage-label">{seg.title} <small>{seg.start_turn}턴~</small></span><meter min={0} max={100} value={seg.rate ?? 0} aria-label={`${seg.title} 도달률`} /><span className="a-stage-value">{rateText(seg.rate)}</span></div>)}
            <details><summary>구간별 수치 표로 보기</summary><div className="a-table-scroll"><table><thead><tr><th>구간</th><th>시작 턴</th><th>도달 대화</th><th>도달률</th></tr></thead><tbody>{data.segments.segments.map(seg => <tr key={seg.id}><th>{seg.title}</th><td>{seg.start_turn}</td><td>{number(seg.reached)}</td><td>{rateText(seg.rate)}</td></tr>)}</tbody></table></div></details>
          </> : <p className="a-empty">선택한 기간에 현재 장면 세트로 시작한 대화가 없어요.</p>}
        </section>}
        <section className="a-kpis" aria-label="공유 지표">{[
          ['링크 공유 버튼', number(share.share_clicks), '결과 화면에서 버튼을 누른 횟수'],
          ['이미지 저장 버튼', number(share.image_save_clicks), '결과 화면에서 버튼을 누른 횟수'],
          ['공유 링크 열기', number(share.link_opens), '공유 링크로 열린 세션 수'],
          ['링크로 체험 시작', number(share.link_start_sessions), `공유 링크 열기 대비 ${percent(share.link_start_sessions, share.link_opens)}`],
        ].map(([label, value, help]) => <article className="a-kpi" key={label}><h2>{label}</h2><strong>{value}</strong><p>{help}</p></article>)}</section>
        <p className="a-notice">공유 버튼은 누른 횟수이며 외부에 실제로 올렸는지는 알 수 없어요. 공유 이벤트는 대화와 연결되지 않아 샘플 여부를 나누지 않고 모든 데이터 선택에서 같은 값을 보여요.</p>
        <section className="a-panel" aria-labelledby="admin-promo"><h2 id="admin-promo">홍보 콘텐츠 클릭률</h2>
          {!data.promo.applicable ? <p className="a-empty">해당 없음 · 이 작품에는 아직 연결된 홍보 링크가 없어요(결과 화면 영화관 바로가기 주소 미정).</p>
            : !data.promo.impressions && !data.promo.clicks ? <p className="a-empty">선택한 기간에 홍보 카드가 노출되지 않았어요.</p> : <>
              <p>노출은 카드가 화면에 절반 이상 보인 세션 수(세션·콘텐츠당 한 번), 클릭률은 클릭한 세션 ÷ 노출된 세션이에요. 전체: 노출 {number(data.promo.impressions)} · 클릭 {number(data.promo.clicks)}회 · 클릭률 {rateText(data.promo.ctr)}</p>
              {data.promo.contents.map(c => <div className="a-stage" key={c.id}><span className="a-stage-label">{c.label}</span><meter min={0} max={100} value={c.ctr ?? 0} aria-label={`${c.label} 클릭률`} /><span className="a-stage-value">{rateText(c.ctr)} · 노출 {number(c.impressions)}</span></div>)}
              <details><summary>콘텐츠별 수치 표로 보기</summary><div className="a-table-scroll"><table><thead><tr><th>콘텐츠</th><th>노출 세션</th><th>클릭</th><th>클릭 세션</th><th>클릭률</th></tr></thead><tbody>{data.promo.contents.map(c => <tr key={c.id}><th>{c.label}<small>{c.id}</small></th><td>{number(c.impressions)}</td><td>{number(c.clicks)}</td><td>{number(c.click_sessions)}</td><td>{rateText(c.ctr)}</td></tr>)}</tbody></table></div></details>
            </>}
        </section>
        <section className="a-panel" aria-labelledby="admin-endings"><h2 id="admin-endings">엔딩 분포</h2>
          <p>끝난 대화 {number(data.endings.judged)}건의 결말이에요. 서버에 저장된 턴 기록으로 결말 판정 규칙을 다시 적용해 계산해요.{data.endings.unjudged_completed > 0 && ` 판정 대상이 아닌(이전 장면 세트) 끝난 대화 ${number(data.endings.unjudged_completed)}건은 뺐어요.`}</p>
          {data.endings.judged ? <>
            {data.endings.endings.map(item => <div className="a-stage" key={item.id}><span className="a-stage-label">{endingTitle(data.project, item.id)}</span><meter min={0} max={100} value={item.rate ?? 0} aria-label={`${endingTitle(data.project, item.id)} 비율`} /><span className="a-stage-value">{number(item.count)}건 · {rateText(item.rate)}</span></div>)}
            <details><summary>엔딩별 수치 표로 보기</summary><div className="a-table-scroll"><table><thead><tr><th>결말</th><th>ID</th><th>도달</th><th>비율</th></tr></thead><tbody>{data.endings.endings.map(item => <tr key={item.id}><th>{endingTitle(data.project, item.id)}</th><td>{item.id}</td><td>{number(item.count)}</td><td>{rateText(item.rate)}</td></tr>)}</tbody></table></div></details>
          </> : <p className="a-empty">선택한 기간에 결말까지 간 대화가 없어요.</p>}
        </section>
        <section className="a-panel" aria-labelledby="admin-interest"><h2 id="admin-interest">관심 분야 분포</h2>
          {!data.interest.applicable ? <p className="a-empty">해당 없음 · 이 작품은 자유 입력의 관심 분야를 분류하지 않아요.</p>
            : data.interest.free_inputs ? <>
              <p>자유 입력 {number(data.interest.free_inputs)}턴을 AI가 분류한 주제예요(버튼 선택 제외).{data.interest.unclassified > 0 && ` 분류가 저장되지 않은 ${number(data.interest.unclassified)}턴(AI 대체 응답·샘플)은 비율 분모에만 들어가요.`}</p>
              {data.interest.topics.map(topic => <div className="a-stage" key={topic.id}><span className="a-stage-label">{topic.label}</span><meter min={0} max={100} value={topic.rate ?? 0} aria-label={`${topic.label} 비율`} /><span className="a-stage-value">{number(topic.count)}턴 · {rateText(topic.rate)}</span></div>)}
            </> : <p className="a-empty">선택한 기간에 자유 입력 턴이 없어요.</p>}
        </section>
        <section className="a-panel"><h2>일별 대화 시작</h2><p>한국 시간 기준 · 막대를 선택하면 수치를 확인할 수 있습니다.</p><div className="a-chart" aria-label="일별 대화 수">{data.daily.map(point => <div className="a-chart-column" key={point.date}><div className="a-chart-track"><button aria-label={`${point.date}: 대화 ${point.conversations}건`} title={`${point.date}: ${point.conversations}건`} style={{ height: `${Math.max(3, point.conversations / peak * 100)}%` }} onClick={e => e.currentTarget.focus()}><span>{point.conversations}</span></button></div><small>{point.date.slice(5)}</small></div>)}</div><details><summary>일별 수치 표로 보기</summary><div className="a-table-scroll"><table><thead><tr><th>날짜</th><th>시작한 대화</th><th>진행 턴</th></tr></thead><tbody>{data.daily.map(p => <tr key={p.date}><th>{p.date}</th><td>{p.conversations}</td><td>{p.turns}</td></tr>)}</tbody></table></div></details></section>
        <section className="a-panel" aria-labelledby="admin-fallback"><h2 id="admin-fallback">AI 대체 응답 비율 <small>운영용</small></h2>
          <p>AI가 응답해야 했던 턴(고정 연출 제외) 중 AI 실패로 장면 고정 대사가 나간 턴의 비율이에요. 기획서 지표가 아닌 운영 점검용이에요.</p>
          {data.fallback.llm_turns ? <>
            <div className="a-stage"><span className="a-stage-label">대체 응답</span><meter min={0} max={100} value={data.fallback.rate ?? 0} aria-label="AI 대체 응답 비율" /><span className="a-stage-value">{number(data.fallback.fallback_turns)} / {number(data.fallback.llm_turns)}턴 · {rateText(data.fallback.rate)}</span></div>
            {data.fallback.reasons.length > 0 && <div className="a-table-scroll"><table><thead><tr><th>사유 코드</th><th>건수</th></tr></thead><tbody>{data.fallback.reasons.map(r => <tr key={r.code}><th>{r.code}</th><td>{number(r.count)}</td></tr>)}</tbody></table></div>}
          </> : <p className="a-empty">선택한 기간에 AI가 응답한 장면 턴이 없어요.</p>}
        </section>
      </>}
    </main>}
  </div>
}
