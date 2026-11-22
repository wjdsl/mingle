import { ChatIntro } from './ChatIntro'
import { AdminApp } from '../admin/AdminApp'
import { chatIntros } from '../../projects/stories/chatIntros'
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
import { StoryCollection } from './StoryCollection'
import { storyClientMode } from '../../services/storyClient'
import { clearProgress, loadProgress } from '../../services/storyProgress'
import type { SavedProgress } from '../../services/storyProgress'
import { hasCollection, recordEnding } from '../../services/endingCollection'

type Stage = 'intro' | 'setup' | 'chat' | 'result' | 'collection'
function readProject() { return projects.find(p => window.location.hash.split('/')[2] === p.id) }
function openHome() { window.location.hash = '/' }

function Experience({ project }: { project: StoryProject }) {
  const [stage, setStage] = useState<Stage>('intro')
  const stageRef = useRef<Stage>('intro')
  const [name, setName] = useState(project.defaultName)
  // 이어하기(냉장고·구름섬): 소개 화면에 올 때마다 이 기기의 저장 기록을 다시 읽는다.
  const [resume, setResume] = useState<SavedProgress | null>(null)
  // 서버가 마지막 장면에서 정한 결말 ID(API·서버 Mock 모드). 브라우저 Mock은 없음 → 고정 샘플 결과.
  const [ending, setEnding] = useState<string | null>(null)
  function finish(result?: string) {
    setEnding(result ?? null)
    if (result && hasCollection(project.id)) recordEnding(project.id, result)
    go('result')
  }
  const saved = project.id !== 'puruma' && stage === 'intro' ? loadProgress(project.id, storyClientMode()) : null
  function startChat(nextName: string, from: SavedProgress | null) { setName(nextName); setResume(from); setEnding(null); setSession(s => s + 1); setStarted(true); setSurface('chat'); go('chat') }
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
    <AppShell immersive={chatting} project={project} onBack={stage === 'intro' ? undefined : back} onHome={home}>
      {stage === 'intro' && <ProjectIntro project={project} saved={saved} onStart={() => go('setup')} onResume={() => saved && startChat(saved.name, saved)} onCollection={hasCollection(project.id) ? () => go('collection') : undefined} />}
      {stage === 'setup' && <ProjectSetup project={project} initialName={name} onStart={n => { clearProgress(project.id); startChat(n, null) }} />}
      {started && <div className="p-session" hidden={stage !== 'chat'} key={session}><ChatIntro config={chatIntros[project.id]} active={stage === 'chat'} dataReady={true}>{project.id === 'puruma' ? <ChatScene nickname={name} onHome={openHome} onSurfaceChange={changeSurface} /> : <ChatLayout project={project} name={name} resume={resume} onResult={finish} onRestart={() => { clearProgress(project.id); setResume(null); setSession(s => s + 1) }} />}</ChatIntro></div>}
      {stage === 'result' && <StoryResult project={project} name={name} ending={ending} onRestart={() => go('setup')} onHome={openHome} onCollection={hasCollection(project.id) ? () => go('collection') : undefined} />}
      {stage === 'collection' && hasCollection(project.id) && <StoryCollection project={project} />}
    </AppShell>
    {exit && <ExitDialog onCancel={() => setExit(false)} onLeave={openHome} />}
  </div>
}
export function Platform() {
  const [adminRoute, setAdminRoute] = useState(() => /^#\/admin(?:\/|$)/.test(window.location.hash))
  const [project, setProject] = useState(readProject)
  useEffect(() => { const update = () => setAdminRoute(/^#\/admin(?:\/|$)/.test(window.location.hash)); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update) }, [])
  useEffect(() => { const update = () => { setProject(readProject()); if (window.location.hash !== '#archive') window.scrollTo(0, 0) }; window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update) }, [])
  useEffect(() => { document.title = adminRoute ? '관리자 · MINGLE' : project ? `${project.title} · MINGLE` : 'MINGLE · 이야기 속으로' }, [project, adminRoute])
  return adminRoute ? <AdminApp /> : project ? <Experience key={project.id} project={project} /> : <Home onSelect={p => { window.location.hash = `/project/${p.id}` }} />
}
