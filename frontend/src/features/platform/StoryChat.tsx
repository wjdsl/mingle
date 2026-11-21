import type { StoryClient } from '../../services/storyClient'
import { createSessionStoryClient, storyClientMode } from '../../services/storyClient'
import { DevSourceBadge } from './DevSourceBadge'
import { useContext } from 'react'
import { ChatEntryMessages } from './ChatIntro'
import { SceneImage } from './SceneImage'
import { useLayoutEffect, useRef } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import { ActionButton, CharacterPortrait } from './shared'
import { useStoryChat } from './useStoryChat'
import type { StoryMessage } from './useStoryChat'
import { useEffect, useState } from 'react'
import { loadStoryScenario } from '../../services/apiStoryClient'

export function MessageComposer({ disabled, onSend }: { disabled: boolean; onSend(text: string): void }) {
  const [draft, setDraft] = useState('')
  const composing = useRef(false)
  function send() {
    if (disabled || composing.current || !draft.trim()) return
    onSend(draft.trim()); setDraft('')
  }
  return <form className="p-message-form" onSubmit={event => { event.preventDefault(); send() }}>
    <label className="sr-only" htmlFor="story-message">직접 답하기</label><div><textarea id="story-message" rows={1} value={draft} disabled={disabled} onChange={event => setDraft(Array.from(event.target.value).slice(0, 300).join(''))} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.keyCode !== 229) { event.preventDefault(); send() } }} placeholder="직접 답하기…" aria-describedby="story-input-help" /><button disabled={disabled || !draft.trim()} type="submit" aria-label="전송">↑</button></div>
    <span id="story-input-help">개인정보는 적지 않아도 돼요.<span>{Array.from(draft).length}/300</span></span>
  </form>
}
export function ChatBubble({ message, project, latest }: { message: StoryMessage; project: StoryProject; latest: boolean }) {
  if (message.kind === 'scene_image') return <SceneImage asset={message.asset} />
  if (message.kind === 'system') return <p className="p-event-message"><span>사건 알림</span>{message.text}</p>
  const display = message.text.match(/\[디스플레이: ([^\]]+)\]/)?.[1]
  const spokenText = message.text.replace(/\[디스플레이: [^\]]+\]\s*/g, '').trim()
  const character = project.characters.find(c => c.name === message.speaker)
  const unlinked = message.role === 'character' && message.provider === 'mock'
  return <div className={`p-bubble p-${message.role}`} data-provider={message.provider} data-model={message.model}>
    <div className="p-speaker">{message.role === 'character' && <span className="p-speaker-symbol" aria-hidden="true">{project.id === 'fridge' ? <span className="p-mini-fridge"><CharacterPortrait project={project} compact /></span> : character?.symbol ?? '✦'}</span>}<b>{message.speaker}</b></div>
    <p>{display && <span className="p-display-direction">{display}</span>}{spokenText}</p>{latest && message.reaction && <span className="p-reaction">{message.reaction}</span>}
    {message.provider === 'fixed' && <small className="p-provider-note">고정 연출</small>}
    {unlinked && <small className="p-provider-note">AI 미연결 · 서버 고정 응답</small>}
  </div>
}
// onRestart: 재시도할 수 없는 오류에서 새 세션(새 클라이언트·서버 대화)으로 다시 시작한다. 서버의 기존 대화 기록은 삭제하지 않는다.
export function ChatLayout({ project, name, onResult, client, onRestart }: { client?: StoryClient; project: StoryProject; name: string; onResult(): void; onRestart?(): void }) {
  if (client || storyClientMode() === 'mock') return <StoryConversation project={project} name={name} onResult={onResult} client={client} onRestart={onRestart} />
  return <ScenarioChat project={project} name={name} onResult={onResult} onRestart={onRestart} />
}

function ScenarioChat({ project, name, onResult, onRestart }: { project: StoryProject; name: string; onResult(): void; onRestart?(): void }) {
  const [scenario, setScenario] = useState<StoryProject>()
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    loadStoryScenario(project, name, controller.signal).then(loaded => {
      if (!controller.signal.aborted) setScenario(loaded)
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(true)
    })
    return () => controller.abort()
  }, [project, name, attempt])
  if (scenario) return <StoryConversation project={scenario} name={name} onResult={onResult} onRestart={onRestart} />
  return <main className="p-chat-layout">{failed
    ? <div className="p-error" role="alert"><span>장면을 불러오지 못했어요.</span><button onClick={() => { setFailed(false); setAttempt(old => old + 1) }}>다시 시도</button></div>
    : <p className="p-loading" role="status">장면을 불러오고 있어요</p>}
  </main>
}

function StoryConversation({ project, name, onResult, client, onRestart }: { client?: StoryClient; project: StoryProject; name: string; onResult(): void; onRestart?(): void }) {
  const visibleMessages = useContext(ChatEntryMessages)
  // 세션(key)마다 새 클라이언트 → 새 서버 대화. 기본은 Mock, VITE_STORY_CLIENT=api일 때 실제 API.
  const [sessionClient] = useState(() => client ?? createSessionStoryClient(name))
  const trace = 'trace' in sessionClient ? (sessionClient as { trace: import('../../services/devSource').SourceTrace }).trace : undefined
  const { turn, messages, status, selected, step, send, retry, advance, errorMessage, retryBlocked, retryWait, canRetry } = useStoryChat(project, name, onResult, sessionClient)
  const log = useRef<HTMLDivElement>(null)
  const stream = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const next = useRef<HTMLButtonElement>(null)
  const follow = useRef(true)
  const unit = project.id === 'cloud' ? '미션' : '장면'
  useLayoutEffect(() => { if (turn > 0) heading.current?.focus() }, [turn])
  useLayoutEffect(() => { if (status === 'replied') next.current?.focus({ preventScroll: true }) }, [status])
  useLayoutEffect(() => {
    const element = log.current
    if (!element) return
    // 새 메시지는 보여 주되, 사용자가 과거 대화를 읽는 중에는 위치를 유지한다.
    const scroll = () => { if (follow.current) element.scrollTop = element.scrollHeight }
    scroll()
    const observer = new ResizeObserver(scroll)
    observer.observe(element)
    if (stream.current) observer.observe(stream.current)
    return () => observer.disconnect()
  }, [messages.length, status])
  return <main className="p-chat-layout">
    {trace && <DevSourceBadge trace={trace} />}
    <header className="p-scene-header"><div><span className="p-kicker">{unit} {turn + 1}/{project.steps.length}{status === 'replied' ? ' · 완료' : ''}</span><h1 ref={heading} tabIndex={-1}>{step.title}</h1></div><details className="p-story-details"><summary aria-label="전체 이야기 진행 보기">진행 보기</summary><ol>{project.steps.map((s, i) => <li key={s.title} aria-current={i === turn ? 'step' : undefined}>{i < turn || (i === turn && status === 'replied') ? '✓' : `0${i + 1}`} <span>{s.title}</span>{i === turn && <small>현재 {unit}</small>}</li>)}</ol></details><progress max={project.steps.length} value={turn + (status === 'replied' ? 1 : 0)} aria-label={`${project.steps.length}개 중 ${turn + (status === 'replied' ? 1 : 0)}개 완료`} /></header>
    <div className="p-chat-log" ref={log} tabIndex={0} role="log" aria-label="대화 목록" aria-live="polite" aria-relevant="additions" onScroll={() => { const el = log.current!; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64 }}><div className="p-chat-stream" ref={stream}>{project.id === 'cloud' && <div className="p-team-story-portrait"><CharacterPortrait project={project} name={step.speaker} /></div>}
      {messages.map((message, i) => <div key={i} hidden={i >= visibleMessages}>{(message.kind === undefined || message.kind === 'text') && message.situation && <p className="p-scene-note">{message.situation}</p>}<ChatBubble project={project} message={message} latest={i === messages.length - 1} /></div>)}
      {status === 'loading' && <p className="p-loading" role="status">● ● ● 답변을 준비하고 있어요</p>}
    </div></div>
    <section className="p-composer" aria-label="답변 보내기">
      {status === 'error' && <div className="p-error" role="alert"><span>{errorMessage ?? '답변을 불러오지 못했어요.'}</span>{canRetry ? <button disabled={retryBlocked} onClick={() => void retry()}>{retryBlocked && retryWait > 0 ? `${retryWait}초 후 다시 시도` : '다시 시도'}</button> : onRestart && <button onClick={onRestart}>새로 시작</button>}</div>}
      {status === 'replied' ? <button className="p-primary" ref={next} onClick={() => { follow.current = true; advance() }}>{turn === project.steps.length - 1 ? (project.id === 'fridge' ? '예고편 마무리' : '결과 예시 보기') : '다음 장면'} <span aria-hidden="true">→</span></button> : step.inputMode === 'none' ? <ActionButton disabled={status !== 'idle'} onClick={() => { follow.current = true; send('') }}>마지막 장면 재생</ActionButton> : <>
        {project.id !== 'fridge' && <p className="p-input-label">선택하거나 직접 답해 보세요.</p>}<div className="p-choices">{step.choices.map((c, i) => <ActionButton secondary key={c.label} className={`p-choice ${selected === i ? 'p-selected' : ''}`} aria-pressed={selected === i} disabled={status !== 'idle'} onClick={() => { follow.current = true; send(c.label, i) }}><span className="p-ticket-number">{selected === i ? '✓' : String(i + 1).padStart(2, '0')}</span><span>{c.label}</span><span className="p-ticket-perforation" aria-hidden="true" /></ActionButton>)}</div>
        <MessageComposer disabled={status !== 'idle'} onSend={text => { follow.current = true; send(text) }} />
      </>}
    </section>
  </main>
}
