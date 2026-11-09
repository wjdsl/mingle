import { useLayoutEffect, useRef } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import { ActionButton, CharacterPortrait } from './shared'
import { useStoryChat } from './useStoryChat'
import type { StoryMessage } from './useStoryChat'
import { useState } from 'react'

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
  const character = project.characters.find(c => c.name === message.speaker)
  return <div className={`p-bubble p-${message.role}`}>
    <div className="p-speaker">{message.role === 'character' && <span className="p-speaker-symbol" aria-hidden="true">{project.id === 'fridge' ? <span className="p-mini-fridge"><CharacterPortrait project={project} compact /></span> : character?.symbol ?? '✦'}</span>}<b>{message.speaker}</b></div>
    <p>{message.text}</p>{latest && message.reaction && <span className="p-reaction">{message.reaction}</span>}
  </div>
}
export function ChatLayout({ project, name, onResult }: { project: StoryProject; name: string; onResult(): void }) {
  const { turn, messages, status, selected, step, send, retry, advance } = useStoryChat(project, name, onResult)
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
    <header className="p-scene-header"><div><span className="p-kicker">{unit} {turn + 1}/{project.steps.length}{status === 'replied' ? ' · 완료' : ''}</span><h1 ref={heading} tabIndex={-1}>{step.title}</h1></div><details className="p-story-details"><summary aria-label="전체 이야기 진행 보기">진행 보기</summary><ol>{project.steps.map((s, i) => <li key={s.title} aria-current={i === turn ? 'step' : undefined}>{i < turn || (i === turn && status === 'replied') ? '✓' : `0${i + 1}`} <span>{s.title}</span>{i === turn && <small>현재 {unit}</small>}</li>)}</ol></details><progress max={project.steps.length} value={turn + (status === 'replied' ? 1 : 0)} aria-label={`${project.steps.length}개 중 ${turn + (status === 'replied' ? 1 : 0)}개 완료`} /></header>
    <div className="p-chat-log" ref={log} tabIndex={0} role="log" aria-label="대화 목록" aria-live="polite" aria-relevant="additions" onScroll={() => { const el = log.current!; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64 }}><div className="p-chat-stream" ref={stream}>
      {messages.map((message, i) => <div key={i}>{message.role === 'character' && (i === 0 || messages[i - 1]?.role === 'character') && <p className="p-scene-note">{project.steps[messages.slice(0, i + 1).filter((m, index, all) => m.role === 'character' && (index === 0 || all[index - 1]?.role === 'character')).length - 1]?.situation}</p>}<ChatBubble project={project} message={message} latest={i === messages.length - 1} /></div>)}
      {status === 'loading' && <p className="p-loading" role="status">● ● ● 답변을 준비하고 있어요</p>}
    </div></div>
    <section className="p-composer" aria-label="답변 보내기">
      {status === 'error' && <div className="p-error" role="alert"><span>답변을 불러오지 못했어요.</span><button onClick={() => void retry()}>다시 시도</button></div>}
      {status === 'replied' ? <button className="p-primary" ref={next} onClick={() => { follow.current = true; advance() }}>{turn === project.steps.length - 1 ? '결과 예시 보기' : '다음 장면'} <span aria-hidden="true">→</span></button> : <>
        <p className="p-input-label">선택하거나 직접 답해 보세요.</p><div className="p-choices">{step.choices.map((c, i) => <ActionButton secondary key={c.label} className={`p-choice ${selected === i ? 'p-selected' : ''}`} aria-pressed={selected === i} disabled={status !== 'idle'} onClick={() => { follow.current = true; send(c.label, i) }}>{c.label}{selected === i && <span>✓</span>}</ActionButton>)}</div>
        <MessageComposer disabled={status !== 'idle'} onSend={text => { follow.current = true; send(text) }} />
      </>}
    </section>
  </main>
}
