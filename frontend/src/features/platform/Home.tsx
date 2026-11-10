import { teamGithubUrl } from '../../projects/site'
import { FeedbackButton } from './FeedbackButton'
import fridgeScene from '../../assets/fridge/fridge-smug.webp'
import { projects } from '../../projects/stories/catalog'
import type { StoryProject } from '../../projects/stories/catalog'
import { CharacterPortrait } from './shared'

export const summaries: Record<string, string> = {
  puruma: '길을 잃은 신입생 푸르마의 선배가 되어 주세요.',
  fridge: '중고 냉장고 속 회장님과 수상한 동거를 시작해요.',
  cloud: '다섯 대원과 힘을 모아 흔들리는 하늘섬을 구해요.',
}
export function ProjectCard({ project, onSelect }: { project: StoryProject; onSelect(): void }) {
  return <button className={`p-project-card theme-${project.id}`} onClick={onSelect} aria-label={`${project.title} 작품 보기`}>
    <div className="p-card-title"><span className="p-volume">0{project.number.replace(/^0/, '')}</span><h3>{project.title}</h3></div>
    <div className="p-poster"><span className="p-poster-genre">{project.genre}</span><>{project.id === 'fridge' ? <img className="p-fridge-cover" src={fridgeScene} alt="원룸에서 자신만만한 표정을 짓는 냉장고 회장" /> : <CharacterPortrait project={project} />}</><span className="p-poster-tag">{project.hook}</span></div>
    <div className="p-card-copy"><p>{summaries[project.id]}</p></div>
  </button>
}
export function Home({ onSelect }: { onSelect(project: StoryProject): void }) {
  return <div className="p-home">
    <header className="p-home-header"><a className="p-wordmark" href="#/" aria-label="MINGLE 홈">mingle<span>✳</span></a><FeedbackButton /></header>
    <main><section className="p-editorial-hero"><span className="p-kicker">INTERACTIVE STORY ARCHIVE</span><h1>이야기 속으로,<br /><span>당신의 차례.</span></h1><p>캐릭터와 대화하며 새로운 세계를 만나 보세요.</p><span className="p-hero-star" aria-hidden="true">✳</span></section>
      <section className="p-archive" id="archive" aria-labelledby="archive-heading"><div className="p-section-heading"><h2 id="archive-heading">지금 만날 이야기 <sup>03</sup></h2></div><div className="p-project-grid">{projects.map(project => <ProjectCard key={project.id} project={project} onSelect={() => onSelect(project)} />)}<article className="p-project-card p-coming-card" aria-label="다음 작품, 공개 예정"><div className="p-card-title"><span className="p-volume">04</span><h3>다음 이야기</h3></div><div className="p-coming-poster"><span className="p-coming-emblem" aria-hidden="true">✳</span><span className="p-coming-label">COMING SOON</span></div><div className="p-card-copy"><p>새로운 세계를 준비하고 있어요.</p></div></article></div></section>
    </main><footer className="p-home-footer"><div className="p-footer-brand"><span>mingle ✳</span><span>© 2026 MINGLE</span></div><a className="p-github-link" href={teamGithubUrl} target="_blank" rel="noopener noreferrer" aria-label="MINGLE 팀 GitHub 저장소 (새 탭)"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.68.08-.68 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.73.4-1.22.71-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.15A10.8 10.8 0 0 1 12 6.17c.96 0 1.92.13 2.82.38 2.15-1.46 3.1-1.15 3.1-1.15.61 1.55.23 2.7.11 2.98.72.79 1.16 1.79 1.16 3.02 0 4.32-2.64 5.27-5.15 5.55.4.35.76 1.03.76 2.08v3.1c0 .3.2.65.78.54A11.25 11.25 0 0 0 12 .75Z" /></svg><span>팀 GitHub</span><span aria-hidden="true">↗</span></a></footer>
  </div>
}
