import type { StoryProject } from '../../projects/stories/catalog'
import { CharacterPortrait, ResultActions } from './shared'

export function StoryResult({ project, name, onRestart, onHome }: { project: StoryProject; name: string; onRestart(): void; onHome(): void }) {
  const cloud = project.id === 'cloud'
  return <main className="p-result"><article className="p-result-card"><span className="p-result-label">결과 예시</span><CharacterPortrait project={project} name={project.result.character} /><p className="p-result-owner">{name}의 이야기</p><h1>{project.result.title}</h1><p>{cloud ? '동료의 마음을 살피고 함께 나아가는 대원.' : '내일의 도시락을 지켜 줄 동거인이 생겼다. 차가운 냉장고와 조금 따뜻해진 자취방.'}</p></article><p className="p-sample-note">선택·발화를 분석한 결과가 아닌 고정 샘플이에요.</p><ResultActions project={project} onRestart={onRestart} onHome={onHome} /></main>
}
