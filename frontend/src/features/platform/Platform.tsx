import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { projects } from '../../projects/stories/catalog'
import type { StoryProject } from '../../projects/stories/catalog'
import { ChatScene } from '../chat/ChatScene'
import { useViewportHeight } from '../chat/useViewportHeight'
import { Home } from './Home'
import { ProjectIntro, ProjectSetup } from './ProjectEntry'
import { ChatLayout } from './StoryChat'
import { StoryResult } from './StoryResult'
import { AppShell, ExitDialog } from './shared'

type Stage = 'intro' | 'setup' | 'chat' | 'result'
function readProject() { return projects.find(p => window.location.hash.split('/')[2] === p.id) }
function openHome() { window.location.hash = '/' }

function Experience({ project }: { project: StoryProject }) {
  const [stage, setStage] = useState<Stage>('intro')
  const stageRef = useRef<Stage>('intro')
  const [name, setName] = useState(project.defaultName)
  const [session, setSession] = useState(0)
  const [started, setStarted] = useState(false)
  const [surface, setSurface] = useState('chat')
  const [exit, setExit] = useState(false)
  const surfaceBack = useRef<() => void>(() => {})
  const heading = useRef<HTMLDivElement>(null)
  const viewport = useViewportHeight()
  const go = useCallback((next: Stage) => {
    if (stageRef.current === next) return
    window.history.pushState({ mingle: project.id, stage: next }, '', window.location.href)
    stageRef.current = next; setStage(next)
  }, [project.id])
  useEffect(() => {
    window.history.replaceState({ mingle: project.id, stage: 'intro' }, '', window.location.href)
    const pop = () => {
      const next = window.history.state?.mingle === project.id ? window.history.state.stage as Stage : 'intro'
      stageRef.current = next; setStage(next)
    }
    window.addEventListener('popstate', pop)
    return () => window.removeEventListener('popstate', pop)
  }, [project.id])
  useEffect(() => { heading.current?.focus({ preventScroll: true }); window.scrollTo(0, 0) }, [stage])
  const changeSurface = useCallback((next: string, back: () => void) => { setSurface(next); surfaceBack.current = back }, [])
  function home() { if (stage === 'chat' && surface === 'chat') setExit(true); else openHome() }
  function back() {
    if (stage === 'chat' && surface !== 'chat') { surfaceBack.current(); return }
    window.history.back()
  }
  const chatting = stage === 'chat' && (project.id !== 'puruma' || surface === 'chat')
  return <div className={`p-experience theme-${project.id} ${chatting ? 'p-chat-stage' : ''} ${project.id === 'puruma' ? 'p-puruma-experience' : ''}`} ref={heading} tabIndex={-1} style={{ '--viewport-height': `${viewport}px`, ...(chatting ? { height: viewport } : {}) } as CSSProperties}>
    <AppShell project={project} onBack={stage === 'intro' ? undefined : back} onHome={home}>
      {stage === 'intro' && <ProjectIntro project={project} onStart={() => go('setup')} />}
      {stage === 'setup' && <ProjectSetup project={project} initialName={name} onStart={n => { setName(n); setSession(s => s + 1); setStarted(true); setSurface('chat'); go('chat') }} />}
      {started && <div className="p-session" hidden={stage !== 'chat'} key={session}>{project.id === 'puruma' ? <ChatScene nickname={name} onHome={openHome} onSurfaceChange={changeSurface} /> : <ChatLayout project={project} name={name} onResult={() => go('result')} />}</div>}
      {stage === 'result' && <StoryResult project={project} name={name} onRestart={() => go('setup')} onHome={openHome} />}
    </AppShell>
    {exit && <ExitDialog onCancel={() => setExit(false)} onLeave={openHome} />}
  </div>
}
export function Platform() {
  const [project, setProject] = useState(readProject)
  useEffect(() => { const update = () => { setProject(readProject()); if (window.location.hash !== '#archive') window.scrollTo(0, 0) }; window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update) }, [])
  useEffect(() => { document.title = project ? `${project.title} · MINGLE` : 'MINGLE · 이야기 속으로' }, [project])
  return project ? <Experience key={project.id} project={project} /> : <Home onSelect={p => { window.location.hash = `/project/${p.id}` }} />
}
