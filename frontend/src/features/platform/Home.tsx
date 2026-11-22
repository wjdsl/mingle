import { teamGithubUrl } from '../../projects/site'
import { FeedbackButton } from './FeedbackButton'
import fridgeScene from '../../assets/fridge/fridge-smug.webp'
import cloudScene from '../../assets/cloud/sky-islands.webp'
import { projects } from '../../projects/stories/catalog'
import type { StoryProject } from '../../projects/stories/catalog'
import { CharacterPortrait } from './shared'
import { storyClientMode } from '../../services/storyClient'
import { loadProgress } from '../../services/storyProgress'

export const summaries: Record<string, string> = {
  puruma: '길을 잃은 신입생 푸르마의 선배가 되어 주세요.',
  fridge: '중고 냉장고 속 회장님과 수상한 동거를 시작해요.',
  cloud: '다섯 대원과 힘을 모아 흔들리는 하늘섬을 구해요.',
}
export function ProjectCard({ project, onSelect }: { project: StoryProject; onSelect(): void }) {
  // 이 기기에 진행 중인 기록이 있으면 표시한다(FR-04). 이어하기 버튼은 작품 소개 화면에 있다.
  const saved = project.id === 'puruma' ? null : loadProgress(project.id, storyClientMode())
  const resumeText = saved ? `이어서 하기 · ${project.id === 'cloud' ? '미션' : '장면'} ${saved.completedTurns + 1}부터` : ''
  return <button className={`p-project-card theme-${project.id}`} onClick={onSelect} aria-label={`${project.title} 작품 보기${saved ? `, ${resumeText}` : ''}`}>
    {saved && <span className="p-progress-badge" aria-hidden="true">{resumeText}</span>}
    <span className="p-book-label">STORY {project.number} / {project.genre}</span>
    <div className="p-poster">{project.id === 'fridge' ? <img className="p-fridge-cover" src={fridgeScene} alt="원룸에서 자신만만한 표정을 짓는 냉장고 회장" /> : project.id === 'cloud' ? <img className="p-cloud-cover" src={cloudScene} alt="구름 위에 떠 있는 하늘섬들과 출발을 기다리는 구조선" /> : <CharacterPortrait project={project} />}</div>
    <h3>{project.id === 'fridge' ? <>우리 집 냉장고가<br />재벌 회장님이다</> : project.title}</h3><p className="p-book-description">{summaries[project.id]}</p>
  </button>
}
export function Home({ onSelect }: { onSelect(project: StoryProject): void }) {
  return <div className="p-home">
    <header className="p-home-header"><a className="p-wordmark" href="#/" aria-label="MINGLE 홈">mingle</a><FeedbackButton /></header>
    <main><section className="p-editorial-hero"><span className="p-kicker">INTERACTIVE STORY LIBRARY</span><h1>오늘은, 어떤 이야기의<br />주인공이 되어 볼까요?</h1><p>한 장을 고르고, 캐릭터에게 말을 걸어 보세요.</p></section>
      <section className="p-archive" id="archive" aria-labelledby="archive-heading"><div className="p-section-heading"><h2 id="archive-heading">지금 펼칠 이야기</h2><span className="p-story-count">03 STORIES</span></div><div className="p-project-grid">{projects.map(project => <ProjectCard key={project.id} project={project} onSelect={() => onSelect(project)} />)}</div><aside className="p-next-book" aria-label="다음 작품 공개 예정"><b>COMING SOON</b><p>다음 책장은 아직 쓰는 중이에요.</p><span>새로운 세계를 준비하고 있어요.</span></aside></section>
    </main><footer className="p-home-footer"><div className="p-footer-brand"><span>mingle ✳</span><span>© 2026 MINGLE</span></div><a className="p-github-link" href={teamGithubUrl} target="_blank" rel="noopener noreferrer" aria-label="MINGLE 팀 GitHub 저장소 (새 탭)"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.68.08-.68 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.73.4-1.22.71-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.15A10.8 10.8 0 0 1 12 6.17c.96 0 1.92.13 2.82.38 2.15-1.46 3.1-1.15 3.1-1.15.61 1.55.23 2.7.11 2.98.72.79 1.16 1.79 1.16 3.02 0 4.32-2.64 5.27-5.15 5.55.4.35.76 1.03.76 2.08v3.1c0 .3.2.65.78.54A11.25 11.25 0 0 0 12 .75Z" /></svg><span>팀 GitHub</span><span aria-hidden="true">↗</span></a></footer>
  </div>
}
