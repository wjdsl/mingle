import { useRef, useState } from 'react'
import { storyClientMode } from '../../services/storyClient'
import type { StoryProject } from '../../projects/stories/catalog'
import { findEnding } from '../../services/endingCollection'
import { downloadBlob, renderResultImage } from '../../services/resultImage'
import { shareEvents } from '../../services/shareEvents'
import { ActionButton, CharacterPortrait, ResultActions } from './shared'

const SAMPLE_NOTE = '선택·발화를 분석한 결과가 아닌 고정 샘플이에요.'
const JUDGED_NOTE = '그동안의 선택과 답변으로 정해진 결과예요.'

// ending: 서버가 마지막 장면에서 정한 결말 ID(API·서버 Mock 모드). 없으면(브라우저 Mock) 기존 고정 샘플을 보여 준다.
export function StoryResult({ project, name, ending, onRestart, onHome, onCollection }: { project: StoryProject; name: string; ending?: string | null; onRestart(): void; onHome(): void; onCollection?(): void }) {
  const cloud = project.id === 'cloud'
  const judged = findEnding(project.id, ending)
  const sample = !judged && project.id !== 'fridge'
  const title = judged?.title ?? project.result.title
  const text = judged ? judged.description : cloud ? '동료의 마음을 살피고 함께 나아가는 대원.' : storyClientMode() === 'mock' ? project.result.text : '냉장고 회장님의 예고편을 마쳤어요.'
  const kicker = judged ? (cloud ? '나와 닮은 대원' : '회장님과의 관계') : undefined
  const note = judged ? JUDGED_NOTE : SAMPLE_NOTE
  const card = useRef<HTMLElement>(null)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  async function saveImage() {
    shareEvents.record(project.id, 'image_save_click')
    const element = card.current
    const img = element?.querySelector('img')
    if (!element || !img || saving) return
    setSaving(true); setSaveStatus('이미지를 만들고 있어요…')
    try {
      const style = getComputedStyle(element)
      const token = (prop: string, fallback: string) => style.getPropertyValue(prop).trim() || fallback
      // 호칭은 넣지 않는다. 고정 샘플이면 화면과 같은 '결과 예시'·안내를 이미지에도 남긴다.
      const blob = await renderResultImage({
        projectTitle: project.title,
        title,
        text,
        imageSrc: img.currentSrc || img.src,
        label: sample ? '결과 예시' : kicker,
        note,
        colors: { bg: token('--w-bg', '#f5f5f5'), surface: token('--w-surface', '#ffffff'), ink: token('--w-ink', '#222222'), accent: token('--w-secondary', '#333333') },
        font: getComputedStyle(element.querySelector('h1') ?? element).fontFamily || 'sans-serif',
      })
      downloadBlob(blob, `mingle-${project.id}-result.png`)
      setSaveStatus('결과 이미지를 저장했어요.')
    } catch {
      setSaveStatus('이미지를 저장하지 못했어요. 화면을 캡처해 주세요.')
    } finally { setSaving(false) }
  }
  const address = judged?.address?.replace('{호칭}', name)
  return <main className={`p-result ${project.id === 'fridge' ? 'p-fridge-result' : ''}`}><article className="p-result-card" ref={card}>
      {sample && <span className="p-result-label">결과 예시</span>}
      {kicker && <span className="p-result-label">{kicker}</span>}
      <CharacterPortrait project={project} name={judged?.character ?? project.result.character} />
      {(sample || (judged && cloud)) && <p className="p-result-owner">{name}의 이야기</p>}
      <h1>{title}</h1><p>{text}</p>
      {address && <p className="p-result-owner">회장님이 부르는 말 · {address}</p>}
    </article><p className="p-sample-note">{note}</p>
    <ResultActions project={project} onRestart={onRestart} onHome={onHome}>
      <ActionButton secondary onClick={() => void saveImage()} disabled={saving}>결과 이미지 저장</ActionButton>
      {onCollection && <ActionButton secondary onClick={onCollection}>결말 도감</ActionButton>}
    </ResultActions>
    <p className="p-share-status" role="status">{saveStatus}</p>
  </main>
}
