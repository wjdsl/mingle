import { createContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { ChatIntroConfig } from '../../projects/stories/chatIntros'

export const ChatEntryMessages = createContext<number>(Infinity)

type Phase = 'loading' | 'backgroundReveal' | 'chatReveal' | 'chatReady'
export function SceneBackground({ config }: { config: ChatIntroConfig }) {
 return <div className="p-scene-background" aria-hidden="true">{config.background && <img src={config.background} alt="" onError={e => { e.currentTarget.hidden = true }} />}<div /></div>
}
export function ChatIntro({ config, active, dataReady, children }: { config: ChatIntroConfig; active: boolean; dataReady: boolean; children: ReactNode }) {
 const [visibleMessages, setVisibleMessages] = useState(0)
 const [phase, setPhase] = useState<Phase>('loading')
 const [imageReady, setImageReady] = useState(!config.background)
 const [minimumElapsed, setMinimumElapsed] = useState(false)
 const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
 const content = useRef<HTMLDivElement>(null)
 const skip = useRef<HTMLButtonElement>(null)
 const first = useRef(true)
 useEffect(() => {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  const update = () => setReduced(media.matches)
  media.addEventListener('change', update)
  return () => media.removeEventListener('change', update)
 }, [])
 useEffect(() => {
  if (!config.background) return
  const image = new Image()
  let alive = true
  const finish = () => { if (alive) setImageReady(true) }
  image.onload = finish; image.onerror = finish; image.src = config.background
  // 느린 이미지로 대화를 막지 않는다. 실패해도 테마 배경으로 진행한다.
  const timeout = window.setTimeout(finish, 900)
  return () => { alive = false; image.onload = null; image.onerror = null; clearTimeout(timeout) }
 }, [config.background])
 useEffect(() => {
  if (!active || phase !== 'loading') return
  const timer = window.setTimeout(() => setMinimumElapsed(true), 1500)
  return () => clearTimeout(timer)
 }, [active, phase])
 useEffect(() => {
  if (!active || phase === 'chatReady') return
  if (phase === 'loading') {
   if (dataReady && imageReady && minimumElapsed) setPhase(config.messageEntrance ? 'chatReveal' : 'backgroundReveal')
   return
  }
  const timer = window.setTimeout(() => setPhase(phase === 'backgroundReveal' ? 'chatReveal' : 'chatReady'), phase === 'backgroundReveal' ? 1300 : config.messageEntrance ? 2100 : 400)
  return () => clearTimeout(timer)
 }, [active, phase, reduced, dataReady, imageReady, minimumElapsed, config.messageEntrance])
 useEffect(() => {
  if (!active || phase !== 'chatReveal' || !config.messageEntrance) return
  setVisibleMessages(1)
  const second = window.setTimeout(() => setVisibleMessages(2), 650)
  const rest = window.setTimeout(() => setVisibleMessages(Infinity), 1300)
  return () => { clearTimeout(second); clearTimeout(rest) }
 }, [active, phase, config.messageEntrance])
 useEffect(() => {
  if (!active) return
  if (phase === 'chatReady') {
   if (first.current) { content.current?.focus({ preventScroll: true }); first.current = false }
  } else skip.current?.focus({ preventScroll: true })
 }, [active, phase])
 return <div className="p-chat-entry" data-phase={phase} data-reduced={reduced} data-message-entrance={Boolean(config.messageEntrance)}>
  {phase !== 'chatReady' && !(config.messageEntrance && phase === 'chatReveal') && <section className="p-chat-intro" aria-label="이야기 도입">
   {!config.messageEntrance && <SceneBackground config={config} />}
   <div className="p-intro-atmosphere" role="status" aria-live="polite"><span className="sr-only">이야기를 준비하고 있어요</span><span className="p-intro-dots" aria-hidden="true"><i /><i /><i /></span></div>
   <button className="p-intro-skip" ref={skip} disabled={!dataReady} onClick={() => setPhase('chatReady')}>건너뛰기 →</button>
  </section>}
  <div className="p-chat-entry-content" ref={content} tabIndex={-1} inert={phase !== 'chatReady'} aria-hidden={phase !== 'chatReady'}><ChatEntryMessages.Provider value={config.messageEntrance && phase !== 'chatReady' ? visibleMessages : Infinity}>{children}</ChatEntryMessages.Provider></div>
 </div>
}
