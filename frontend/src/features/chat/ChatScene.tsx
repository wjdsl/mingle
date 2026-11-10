import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { project } from '../../projects/puruma/config'
import { choices } from '../../projects/puruma/mockConversation'
import { mockConversationClient } from '../../services/mockConversationClient'
import { geminiConversationClient } from '../../services/geminiConversationClient'
import { useChat } from './useChat'
import type { ChatState, Choice, ConversationMode, Emotion, Message } from './types'
import { EndingCollection } from '../endings/EndingCollection'
import { useViewportHeight } from './useViewportHeight'

type View = 'chat' | 'notes' | 'endings' | 'result'

function UtilityNavigation({ onNavigate }: { onNavigate(view: 'notes' | 'endings'): void }) {
  return <nav className="utility-nav" aria-label="기록 메뉴">
    <button onClick={() => onNavigate('notes')} aria-label="유저노트 열기" title="유저노트"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M6 3h14v18H6zM3 7h6M3 12h6M3 17h6M11 8h5M11 12h5" /></svg></button>
    <button onClick={() => onNavigate('endings')} aria-label="엔딩 도감 열기" title="엔딩 도감"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 5C8 2 4 3 2 4v16c3-1 7-1 10 1 3-2 7-2 10-1V4c-2-1-6-2-10 1Zm0 0v16M6 8h3M6 12h3M15 8h3M15 12h3" /></svg></button>
  </nav>
}

function ProgressHeader({ state, onNavigate }: { state: ChatState; onNavigate(view: 'notes' | 'endings'): void }) {
  return <header className="diary-header">
    <div className="progress-card">
      <div className="progress-label"><span><b>01</b> {project.chapter}</span><span>체험 <strong>{Math.min(state.completedTurns + 1, project.demoTurns)}</strong> / {project.demoTurns}</span><UtilityNavigation onNavigate={onNavigate} /></div>
      <div className="progress-track" role="progressbar" aria-label="개강 구간 진행" aria-valuemin={0} aria-valuemax={2} aria-valuenow={state.completedTurns} aria-valuetext={`개강 ${state.completedTurns} / 2턴 완료`}><span style={{ width: `${state.completedTurns / project.demoTurns * 100}%` }} /></div>
      <div className="progress-foot"><span>첫 수업, 길을 잃었어요!</span><span>{state.completedTurns}/2턴 완료</span></div>
    </div>
  </header>
}

function MessageBubble({ message, latest, currentEmotion, nickname }: { message: Message; latest: boolean; currentEmotion: Emotion; nickname: string }) {
  if (message.role === 'user') return <div className="message user"><span className="speaker">나 · {nickname}</span><p>{message.text}</p></div>
  const emotion = message.emotion ?? (latest ? currentEmotion : 'confused')
  const comic = message.text.includes('또각')
  return <div className={`message character ${latest ? 'latest-reply' : ''} ${comic ? 'comic-reply' : ''}`}>
    <div className={`message-portrait reaction-${emotion}`}>
      <img src={project.images[emotion]} alt={`푸르마 · ${emotion === 'confused' ? '갸우뚱하는 모습' : emotion === 'happy' ? '기쁜 모습' : '반짝이는 모습'}`} />
      {latest && <span className="reaction-symbol" aria-hidden="true">{emotion === 'confused' ? '?' : emotion === 'happy' ? '♥' : '✦'}</span>}
    </div>
    <div className="message-body"><div className="speaker-row"><span className="speaker">푸르마</span>{latest && <span className="reaction-caption">{comic ? '또각…!' : emotion === 'confused' ? '선배, SOS!' : emotion === 'happy' ? '히히힝!' : '반짝, 알아냈어요!'}</span>}</div><p>{message.text}</p></div>
  </div>
}
function MessageList({ state, nickname }: { state: ChatState; nickname: string }) {
  const container = useRef<HTMLDivElement>(null)
  const stream = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const element = container.current!
    const scrollToBottom = () => { element.scrollTop = element.scrollHeight }
    scrollToBottom()
    const observer = new ResizeObserver(scrollToBottom)
    observer.observe(element)
    if (stream.current) observer.observe(stream.current)
    return () => observer.disconnect()
  }, [state.messages.length, state.status])
  return <div className="message-region">
    <div className="message-list" ref={container} role="log" aria-label="대화 목록" aria-live="polite" aria-relevant="additions" tabIndex={0}>
      <div className="message-stream" ref={stream}>
      <p className="conversation-date"><span>개강 첫날 · 첫 수업, 길을 잃었어요!</span></p>
      {state.messages.map((message, index) => <MessageBubble key={message.id} message={{ ...message, text: message.role === 'character' ? message.text.replaceAll('선배', nickname) : message.text }} latest={message.role === 'character' && index === state.messages.length - 1} currentEmotion={state.emotion} nickname={nickname} />)}
      {state.status === 'responding' && <p className="typing" role="status"><span aria-hidden="true">● ● ●</span> 푸르마가 생각하고 있어요</p>}
      </div>
    </div>
  </div>
}

function ChoiceList({ items, disabled, selectedId, onChoose }: { items: Choice[]; disabled: boolean; selectedId?: string; onChoose(choice: Choice): void }) {
  return <div className="choices" aria-label="답변 선택지">{items.map((choice, index) => <button key={choice.id} className={selectedId === choice.id ? 'is-selected' : ''} aria-pressed={selectedId === choice.id} disabled={disabled} onClick={() => onChoose(choice)}><span className="choice-number">0{index + 1}</span><span className="choice-label">{choice.label}</span>{selectedId === choice.id && <span className="selected-label">선택함</span>}</button>)}</div>
}

export function ChatScene({ nickname = '선배', mode = 'mock', onHome, onSurfaceChange }: { nickname?: string; mode?: ConversationMode; onHome(): void; onSurfaceChange(view: string, back: () => void): void }) {
  const viewportHeight = useViewportHeight()
  const { state, draft, setDraft, validation, send, retry, reset } = useChat(mode === 'gemini' ? geminiConversationClient : mockConversationClient)
  const [view, setView] = useState<View>('chat')
  const returnView = useRef<View>('chat')
  const pageHeading = useRef<HTMLHeadingElement>(null)
  useLayoutEffect(() => { pageHeading.current?.focus() }, [view])
  useEffect(() => { onSurfaceChange(view, () => setView('chat')) }, [view, onSurfaceChange])
  function openUtility(next: 'notes' | 'endings') {
    if (view !== 'notes' && view !== 'endings') returnView.current = view
    setView(next)
  }
  function restart() { reset(); setView('chat') }
  const composing = useRef(false)
  const disabled = state.status !== 'idle'
  function submit() { if (!composing.current) send({ kind: 'text', text: draft }) }
  return <main className={`desktop-canvas integrated-puruma ${view !== 'chat' ? 'puruma-record-view' : ''}`} data-short-viewport={viewportHeight <= 560} style={{ '--viewport-height': `${viewportHeight}px` } as CSSProperties}>
    <div className="diary-shell">
      {(view === 'notes' || view === 'endings' || view === 'result') && <section className="record-screen" aria-label={view === 'notes' ? '유저노트' : view === 'result' ? 'Mock 엔딩 카드' : '엔딩 도감'}>
        <button className="back-button" onClick={() => setView(returnView.current)}>← {returnView.current === 'chat' ? '대화로 돌아가기' : '이전 화면으로'}</button>
        {view !== 'notes' ? <EndingCollection initialPreview={view === 'result'} onHome={onHome} onRestart={restart} /> : <>
          <p className="eyebrow">USER NOTE</p>
          <h2 ref={pageHeading} tabIndex={-1}>유저노트</h2>
          <div className="record-empty note-sheet"><div className="note-sheet-header"><span>나의 캠퍼스 메모</span><span aria-hidden="true">✎</span></div><div className="note-empty-content"><div className="note-doodle"><img src={project.images.happy} alt="" /><span aria-hidden="true">선배의 이야기가<br />궁금해요!</span></div><span className="note-status">아직 기록 없음</span><h3>우리의 이야기가<br />한 장씩 쌓일 곳.</h3><p>함께 나눈 중요한 이야기가 담길 공간이에요.<br />이번 시연에서는 기억을 추출하거나 저장하지 않아요.</p></div><p className="note-sheet-footer">USER NOTE · 비어 있는 첫 페이지</p></div>
          <p className="demo-note">프로토타입 빈 화면 · 실제 수집 데이터 없음</p>
        </>}
      </section>}
      {view === 'chat' && <>
      <ProgressHeader state={state} onNavigate={openUtility} />
      <MessageList state={state} nickname={nickname} />
      <section className="composer" aria-label="메시지 보내기">
        {state.status === 'complete' ? <div className="completion" role="status"><b>첫 번째 기록, 여기까지!</b><p>개강 2턴 체험을 마쳤어요.</p><div className="completion-actions"><button className="restart" onClick={() => { returnView.current = 'chat'; setView('result') }}>결과 예시 보기 →</button><button className="restart" onClick={restart}>다시 체험하기 ↻</button></div></div> : <>
          {state.status === 'error' && <div className="error-notice" role="alert">{mode === 'gemini' ? 'Gemini' : 'Mock'} 응답을 불러오지 못했어요. 진행은 그대로예요.<button onClick={retry}>다시 시도 ↻</button></div>}
          <p className="input-hint">선택하거나 직접 답해 보세요.</p>
          <ChoiceList items={choices[state.completedTurns]} disabled={disabled} selectedId={state.pending?.input.kind === 'choice' ? state.pending.input.choiceId : undefined} onChoose={choice => send({ kind: 'choice', choiceId: choice.id, text: choice.label })} />
          <form onSubmit={event => { event.preventDefault(); submit() }}>
            <label className="sr-only" htmlFor="chat-input">푸르마에게 자유롭게 답하기</label>
            <div className="input-row"><textarea id="chat-input" rows={1} value={draft} disabled={disabled} placeholder="직접 답하기…" aria-describedby="input-count input-note input-error" aria-invalid={Boolean(validation)} onChange={event => setDraft(Array.from(event.target.value).slice(0, 300).join(''))} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }} onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.keyCode !== 229) { event.preventDefault(); submit() }
            }} /><button className="send" disabled={disabled || !draft.trim()} aria-label="전송" type="submit">전송</button></div>
            <div className="input-meta"><span id="input-note">개인정보는 적지 않아도 돼요.</span><span id="input-count">{Array.from(draft).length}/300</span></div>
            <p id="input-error" className="validation" role="status">{validation}</p>
          </form>
        </>}
        {mode === 'gemini' && <p className="demo-note">Gemini 실제 AI · 입력이 Google로 전송돼요 · 새로고침하면 초기화</p>}
      </section>
      </>}
    </div>
  </main>
}
