import { FeedbackButton } from './FeedbackButton'
import fridgePoster from '../../assets/fridge/poster.webp'
import fridgePortrait from '../../assets/fridge/fridge-smug.webp'
import { useEffect, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import purumaImage from '../../assets/puruma/happy.png'
import { shareProject } from '../../services/shareProject'

export function ActionButton({ secondary = false, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { secondary?: boolean }) {
  return <button {...props} className={`${secondary ? 'p-secondary' : 'p-primary'} ${className}`} />
}

export function DemoNotice({ compact = false }: { compact?: boolean }) {
  if (!compact) return <p className="p-demo-notice">실제 AI 없이 정해진 대사로 답하는 체험이에요.<br />진행은 새로고침하면 초기화돼요.</p>
  return <details className="p-demo-details"><summary>시연 모드 <span aria-hidden="true">ⓘ</span></summary><p>실제 AI는 연결되어 있지 않아요. 직접 입력에도 정해진 대사로 답해요. 진행은 새로고침하면 초기화돼요.</p></details>
}

export function AppShell({ project, onBack, onHome, children, immersive = false }: { immersive?: boolean; project: StoryProject; onBack?: () => void; onHome(): void; children: ReactNode }) {
  return <div className={`p-work theme-${project.id}`}>
    {immersive ? <header className="p-work-header p-immersive-header">
      <button className="p-icon-button" onClick={onBack} aria-label="이전 화면으로">←</button>
      <span className="p-chat-work-title" title={project.title}>{project.id === 'fridge' ? '냉장고 회장님' : project.title}</span>
      <details className="p-chat-menu"><summary aria-label="채팅 메뉴">···</summary><div><button onClick={onHome}>MINGLE 홈으로</button><FeedbackButton /><p>시연 모드 · 실제 AI 없이 정해진 대사로 진행돼요. 새로고침하면 초기화돼요.</p></div></details>
    </header> : <header className="p-work-header"><div className="p-header-navigation">
      {onBack && <button className="p-icon-button" onClick={onBack} aria-label="이전 화면으로">←</button>}
      <button className="p-wordmark p-home-button" onClick={onHome} aria-label="MINGLE 홈으로">mingle<span>✳</span></button>
    </div><div className="p-header-tools"><FeedbackButton compact /><DemoNotice compact /></div></header>}{children}
  </div>
}

export function ExitDialog({ onCancel, onLeave }: { onCancel(): void; onLeave(): void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog className="p-exit-dialog" ref={dialog} onCancel={event => { event.preventDefault(); onCancel() }} aria-labelledby="exit-heading">
    <h2 id="exit-heading">홈으로 돌아갈까요?</h2><p>지금 대화는 저장되지 않아요.<br />다시 들어오면 처음부터 시작해요.</p>
    <div><ActionButton secondary onClick={onCancel}>계속 대화하기</ActionButton><ActionButton onClick={onLeave}>홈으로</ActionButton></div>
  </dialog>
}

export function ResultActions({ project, onRestart, onHome, children }: { project: StoryProject; onRestart(): void; onHome(): void; children?: ReactNode }) {
  const [feedback, setFeedback] = useState('')
  const [manualLink, setManualLink] = useState('')
  async function share() {
    const result = await shareProject(project.title, project.id)
    setFeedback(result.message); setManualLink(result.manualLink ?? '')
  }
  return <div className="p-result-actions">
    <ActionButton onClick={onHome}>다른 작품 보기 <span aria-hidden="true">→</span></ActionButton>
    <div className="p-secondary-actions"><ActionButton secondary onClick={onRestart}>다시 체험하기</ActionButton><ActionButton secondary onClick={() => void share()}>작품 링크 공유</ActionButton>{children}</div>
    <p className="p-share-status" role="status">{feedback}</p>
    {manualLink && <label className="p-manual-link">공유 링크<input value={manualLink} readOnly onFocus={e => e.target.select()} /></label>}
  </div>
}

export function CharacterPortrait({ project, name, compact = false }: { project: StoryProject; name?: string; compact?: boolean }) {
  if (project.id === 'puruma') return <img className="p-puruma-image" src={purumaImage} alt="신입생 푸르마" />
  if (project.id === 'fridge') return <img className={`p-fridge-art ${compact ? 'p-compact' : ''}`} src={compact ? fridgePortrait : fridgePoster} alt={compact ? '원룸의 냉장고 회장' : '우리 집 냉장고가 재벌 회장님이다 공식 제공 포스터'} />
  const character = project.characters.find(c => c.name === name) ?? project.characters[0]
  return <div className={`p-cloud-art ${compact ? 'p-compact' : ''}`} role="img" aria-label={`${character.name} 구조대원 콘셉트 심벌`}><span className="p-cloud-puff p-puff-one" /><span className="p-cloud-puff p-puff-two" /><span className="p-cloud-island"><span className="p-cloud-flag" aria-hidden="true">⚑</span><span className="p-cloud-face" aria-hidden="true">{character.symbol}<small>• ‿ •</small></span></span><span className="p-cloud-orbit" aria-hidden="true">✧</span></div>
}
