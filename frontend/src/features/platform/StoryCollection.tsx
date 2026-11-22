import type { StoryProject } from '../../projects/stories/catalog'
import { ENDINGS, loadAcquired } from '../../services/endingCollection'
import type { CollectionProject } from '../../services/endingCollection'

// 냉장고·구름섬 결말 도감 (FR-44·45). 얻지 못한 결말은 이름을 가린다.
// 결말 판정이 아직 없어 지금은 모든 칸이 잠겨 있다. 판정이 연결되면 얻은 결말이 자동으로 열린다.
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
    <p className="p-field-help">얻은 결말은 이 기기에 저장되고, 다시 시작해도 지워지지 않아요. 결말 판정은 준비 중이라 지금은 획득할 수 없어요.</p>
  </main>
}
