import type { StoryProject } from '../../projects/stories/catalog'
import { ENDINGS, loadAcquired } from '../../services/endingCollection'
import type { CollectionProject } from '../../services/endingCollection'
import { storyClientMode } from '../../services/storyClient'

// 냉장고·구름섬 결말 도감 (FR-44·45). 얻지 못한 결말은 이름을 가린다.
// 결말은 서버가 마지막 장면에서 정하고(API·서버 Mock 모드), 결과 화면으로 갈 때 기록된다.
export function StoryCollection({ project }: { project: StoryProject }) {
  const endings = ENDINGS[project.id as CollectionProject]
  const acquired = new Set(loadAcquired(project.id as CollectionProject))
  const label = project.id === 'cloud' ? '대원 타입' : '관계 결말'
  return <main className="p-collection">
    <div className="p-entry-heading"><p className="p-kicker">{project.title}</p><h1>결말 도감</h1></div>
    <p className="p-collection-count" aria-live="polite">{label} {acquired.size} / {endings.length} 획득</p>
    <ul className="p-collection-grid">{endings.map((ending, i) => {
      const open = acquired.has(ending.id)
      return <li key={ending.id} className={open ? 'p-unlocked' : 'p-locked'} aria-label={open ? `${ending.title} 획득` : `미획득 결말 ${i + 1}`}>
        <span className="p-collection-number">{String(i + 1).padStart(2, '0')}</span>
        <b>{open ? ending.title : '???'}</b>
        <small>{open ? '획득한 결말' : '아직 만나지 못한 결말'}</small>
      </li>
    })}</ul>
    <p className="p-field-help">얻은 결말은 이 기기에 저장되고, 다시 시작해도 지워지지 않아요. {storyClientMode() === 'mock' ? '지금은 정해진 대사로 진행하는 체험 모드라 결말을 얻을 수 없어요.' : '결말은 이야기를 끝까지 마치면 그동안의 선택과 답변으로 정해져요.'}</p>
  </main>
}
