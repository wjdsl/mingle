import { useLayoutEffect, useRef, useState } from 'react'
import graduation from '../../assets/puruma/graduation.png'
import './endings.css'
import { ResultActions, ActionButton } from '../platform/shared'
import { projects } from '../../projects/stories/catalog'

type Ending = { endingId: string; title: string; description: string; image: string }
// PM 기획서 v0.2 §6.1의 후보 예시. 실제 판정·획득 데이터가 아니다.
const sampleEnding: Ending = {
  endingId: 'preview-survivor',
  title: '종강 생존 푸르마',
  description: '푸르마는 무사히 한 학기를 버텼어요! 완벽하진 않았지만 선배와 함께라서 괜찮았어요.',
  image: graduation,
}

function LockIcon() {
  return <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="7" y="14" width="18" height="14" rx="2" /><path d="M11 14V9a5 5 0 0 1 10 0v5M16 20v3" /></svg>
}

export function EndingCard({ ending }: { ending: Ending }) {
  return <article className="graduation-card" aria-label="졸업 기념 엔딩 카드">
    <span className="p-result-label">결과 예시 · 디자인 샘플</span>
    <div className="graduation-portrait"><img src={ending.image} alt="학사모를 쓰고 꽃다발을 든 푸르마" /></div>
    <h3>{ending.title}</h3><p className="ending-description">선배와 함께라서 무사히 버틴 한 학기.<br />푸르마의 졸업 기념 카드예요.</p>
  </article>
}

export function EndingCollection({ initialPreview = false, onHome, onRestart }: { initialPreview?: boolean; onHome(): void; onRestart(): void }) {
  const [sampleMode, setSampleMode] = useState(false)
  const [selected, setSelected] = useState<Ending | null>(initialPreview ? sampleEnding : null)
  const heading = useRef<HTMLHeadingElement>(null)
  const didMount = useRef(false)
  useLayoutEffect(() => {
    if (didMount.current) heading.current?.focus()
    didMount.current = true
  }, [selected])

  if (selected) return <div className="ending-preview">
    <h2 className="sr-only" ref={heading} tabIndex={-1}>푸르마 결과 예시</h2>
    <EndingCard ending={selected} />
    <p className="p-sample-note">실제 획득·엔딩 판정이 아닌 디자인 샘플이에요.</p>
    <ResultActions project={projects[0]} onHome={onHome} onRestart={onRestart}><ActionButton secondary onClick={() => setSelected(null)}>앨범 보기</ActionButton></ResultActions>
  </div>

  return <div className="ending-collection">
    <p className="eyebrow">OUR CAMPUS MEMORIES / U08</p>
    <h2 ref={heading} tabIndex={-1}>졸업 앨범</h2>
    <p className="album-introduction">함께 보낸 한 학기,<br />푸르마의 여러 모습을 한 장씩 모아요.</p>
    <div className="album-modes" role="group" aria-label="앨범 표시 모드">
      <button aria-pressed={!sampleMode} onClick={() => setSampleMode(false)}>내 앨범</button>
      <button aria-pressed={sampleMode} onClick={() => setSampleMode(true)}>디자인 샘플</button>
    </div>
    {sampleMode && <p className="sample-notice" role="status">샘플 1장 · 실제 획득 기록에는 반영되지 않아요.</p>}
    <section className="album-book" aria-label={sampleMode ? '졸업 앨범 디자인 샘플' : '미획득 엔딩 앨범'}>
      <div className="album-binding" aria-hidden="true"><i /><i /><i /><i /></div>
      <div className="album-page">
        <header className="album-page-header"><span>푸르마의 졸업 앨범</span><span>{sampleMode ? 'SAMPLE' : '획득 0개'}</span></header>
        <div className="album-grid">
          {Array.from({ length: 4 }, (_, index) => <div className={`album-slot slot-${index + 1}`} key={index}>
            {sampleMode && index === 0 ? <button className="album-photo unlocked" onClick={() => setSelected(sampleEnding)} aria-label="샘플 종강 생존 푸르마 엔딩 카드 보기">
              <span className="photo-tape" aria-hidden="true" />
              <span className="photo-area"><img src={sampleEnding.image} alt="졸업한 푸르마 샘플" /><span className="sample-photo-label">샘플</span></span>
              <span className="photo-title">종강 생존 푸르마</span><span className="photo-caption">카드 펼쳐 보기 ↗</span>
            </button> : <div className="album-photo locked" aria-label={`미획득 엔딩 자리 ${index + 1}`}>
              <span className="photo-tape" aria-hidden="true" />
              <span className="photo-area"><LockIcon /><span className="locked-stars" aria-hidden="true">???</span></span>
              <span className="photo-title">미획득 엔딩</span><span className="photo-caption">아직 만나지 못했어요</span>
            </div>}
          </div>)}
        </div>
        <footer className="album-page-footer"><span>TO BE CONTINUED…</span><span>01</span></footer>
      </div>
    </section>
    <p className="album-empty-note">{sampleMode ? '획득 카드와 잠금 카드의 디자인을 비교해 보세요.' : '아직 기록된 엔딩이 없어요. 새로운 이야기가 이곳에 남을 거예요.'}</p>
    <button className="card-preview-button" onClick={() => setSelected(sampleEnding)}>엔딩 카드 디자인 미리보기 <span aria-hidden="true">↗</span></button>
    <p className="demo-note">4칸은 배치 예시 · 엔딩 개수 미확정 · 획득·저장 미연결</p>
  </div>
}
