import { useLayoutEffect, useRef, useState } from 'react'
import graduation from '../../assets/puruma/graduation.png'
import './endings.css'

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
    <div className="card-corners" aria-hidden="true" />
    <p className="card-serial">CAMPUS MEMORY / DESIGN SAMPLE</p>
    <div className="card-heading"><span aria-hidden="true">✦</span><h3>한 학기의 기록</h3><span aria-hidden="true">✦</span></div>
    <p className="card-subtitle">선배와 함께여서, 무사히.</p>
    <div className="graduation-portrait"><img src={ending.image} alt="학사모를 쓰고 꽃다발을 든 푸르마" /><span className="portrait-caption">우리의 첫 학기를 기억하며</span></div>
    <span className="ending-category">재미 엔딩 · 기획 후보 예시</span>
    <h4>{ending.title}</h4>
    <p className="ending-description">{ending.description}</p>
    <div className="card-signature"><span>함께한 선배에게<br /><b>고마워요, 히히힝!</b></span><span className="memory-seal" aria-hidden="true">PURUMA<br /><strong>✦</strong><br />MEMORY</span></div>
    <p className="card-footer">푸르마와 학교 다니기 <span aria-hidden="true">✳</span> mingle</p>
  </article>
}

export function EndingCollection() {
  const [sampleMode, setSampleMode] = useState(false)
  const [selected, setSelected] = useState<Ending | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const didMount = useRef(false)
  useLayoutEffect(() => {
    if (didMount.current) heading.current?.focus()
    didMount.current = true
  }, [selected])

  if (selected) return <div className="ending-preview">
    <p className="eyebrow">ENDING CARD / U06</p>
    <h2 ref={heading} tabIndex={-1}>졸업 기념 카드</h2>
    <p className="sample-notice">디자인 샘플 · 실제 획득 아님</p>
    <EndingCard ending={selected} />
    <button className="primary-action" onClick={() => setSelected(null)}>졸업 앨범으로 돌아가기 <span aria-hidden="true">↩</span></button>
    <p className="demo-note">저장·공유·엔딩 판정은 이후 연결 예정</p>
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
