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
    <div className="p-card-title"><span className="p-volume">0{project.number.replace(/^0/, '')}</span><h3>{project.title}</h3><span className="p-card-arrow" aria-hidden="true">↗</span></div>
    <div className="p-poster"><span className="p-poster-genre">{project.genre}</span><CharacterPortrait project={project} /><span className="p-poster-tag">{project.hook}</span></div>
    <div className="p-card-copy"><p>{summaries[project.id]}</p><span>작품 보기 <span aria-hidden="true">→</span></span></div>
  </button>
}
export function Home({ onSelect }: { onSelect(project: StoryProject): void }) {
  return <div className="p-home">
    <header className="p-home-header"><a className="p-wordmark" href="#/" aria-label="MINGLE 홈">mingle<span>✳</span></a><a className="p-archive-link" href="#archive">작품 둘러보기 <span aria-hidden="true">↙</span></a></header>
    <main><section className="p-editorial-hero"><span className="p-kicker">INTERACTIVE STORY ARCHIVE</span><h1>이야기 속으로,<br /><span>당신의 차례.</span></h1><p>캐릭터와 대화하며 세 가지 세계를 만나 보세요.</p><span className="p-hero-star" aria-hidden="true">✳</span></section>
      <section className="p-archive" id="archive" aria-labelledby="archive-heading"><div className="p-section-heading"><h2 id="archive-heading">지금 만날 이야기 <sup>03</sup></h2><span className="p-demo-badge">시연용 콘텐츠</span></div><div className="p-project-grid">{projects.map(project => <ProjectCard key={project.id} project={project} onSelect={() => onSelect(project)} />)}</div></section>
      <aside className="p-coming"><span>COMING NEXT</span><p>다음 이야기도 이곳에서 만나요.</p><span aria-hidden="true">＋</span></aside>
      <p className="p-home-note">로그인 없이 체험해요. 현재는 실제 AI 없이 정해진 대사로 진행되며, 새로고침하면 초기화돼요.</p>
    </main><footer className="p-home-footer"><span>mingle ✳</span><span>© 2026 MINGLE</span></footer>
  </div>
}
