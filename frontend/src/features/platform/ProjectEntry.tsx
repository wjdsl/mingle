import { storyClientMode } from '../../services/storyClient'
import { purumaStoryMode } from '../../services/apiPurumaStoryClient'
import { useState } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import { ActionButton, CharacterPortrait, DemoNotice } from './shared'
import type { SavedProgress } from '../../services/storyProgress'

const roles: Record<string, string> = { puruma: '푸르마를 돕는 선배', fridge: '회장님과 동거하는 취업 준비생', cloud: '구조대의 새 대원' }
const startLabels: Record<string, string> = { puruma: '푸르마 만나기', fridge: '회장님 만나기', cloud: '구조대 합류하기' }
const shortRoles: Record<string, string> = { 토토: '대장', 비비: '정비 담당', 나나: '구조대원', 키키: '발명가', 두두: '행동파' }

export function ProjectIntro({ project, onStart, saved, onResume, onCollection }: { project: StoryProject; onStart(): void; saved?: SavedProgress | null; onResume?(): void; onCollection?(): void }) {
  const unit = project.id === 'cloud' ? '미션' : project.id === 'puruma' ? '턴' : '장면'
  return <main className="p-intro">
    <div className="p-entry-heading"><p className="p-kicker">{project.genre}</p><h1>{project.title}</h1></div>
    <div className="p-intro-art"><CharacterPortrait project={project} /><span className="p-art-caption">{project.hook}</span></div>
    <div className="p-intro-copy"><p>{project.description}</p><div className="p-intro-facts"><span>{roles[project.id]}</span><span>{project.id === 'puruma' ? (purumaStoryMode() === 'api' ? '10턴 Gemini 체험' : '10턴 Mock 체험') : storyClientMode() === 'api' ? '10턴 Gemini 체험' : project.id === 'cloud' && storyClientMode() === 'mock' ? '3개 미션 체험' : '10턴 Mock 체험'}</span></div>{saved && onResume
      ? <div className="p-resume-actions"><ActionButton onClick={onResume}>이어하기 · {unit} {saved.completedTurns + 1}부터 <span aria-hidden="true">→</span></ActionButton><ActionButton secondary onClick={onStart}>새로 시작</ActionButton><p className="p-field-help">‘{saved.name}’ 호칭으로 하던 이야기가 이 기기에 저장되어 있어요. 새로 시작하면 저장된 진행은 지워져요.</p></div>
      : <ActionButton onClick={onStart}>체험 준비하기 <span aria-hidden="true">→</span></ActionButton>}{onCollection && <button type="button" className="p-text-link" onClick={onCollection}>결말 도감 보기</button>}{project.id !== 'fridge' && <DemoNotice project={project} />}</div>
  </main>
}
export function ProjectSetup({ project, initialName, onStart }: { project: StoryProject; initialName: string; onStart(name: string): void }) {
  const [name, setName] = useState(initialName === project.defaultName ? '' : initialName)
  const cloud = project.id === 'cloud'
  return <main className="p-setup"><p className="p-kicker">{cloud ? '구름섬 구조대에 오신 걸 환영해요' : project.title}</p><h1>어떻게 불러 드릴까요?</h1>
    <section className={`p-team ${cloud ? 'p-team-grid' : ''}`} aria-label="함께할 캐릭터">{project.characters.map(c => <div className="p-teammate" key={c.name}><span className="p-person-symbol" aria-hidden="true">{c.symbol}</span><div><b>{c.name}</b><p>{cloud ? shortRoles[c.name] : c.role}</p></div></div>)}</section>
    {cloud && <details className="p-team-details"><summary>대원들의 성격 알아보기</summary><ul>{project.characters.map(c => <li key={c.name}><b>{c.name}</b> · {c.role}</li>)}</ul></details>}
    <form onSubmit={event => { event.preventDefault(); onStart(name.trim() || project.defaultName) }}><label htmlFor="story-name">이야기에서 사용할 호칭 <span>최대 12자</span></label><input autoComplete="off" id="story-name" value={name} onChange={event => setName(Array.from(event.target.value).slice(0, 12).join(''))} placeholder={`기본 호칭: ${project.defaultName}`} aria-describedby="name-help" /><p id="name-help" className="p-field-help">별명으로도 좋아요. 비워 두면 ‘{project.defaultName}’로 시작해요.</p><ActionButton type="submit">{startLabels[project.id]} <span aria-hidden="true">→</span></ActionButton></form>
  </main>
}
