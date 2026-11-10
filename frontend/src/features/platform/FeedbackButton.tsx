import { useEffect, useId, useRef, useState } from 'react'
import { copyFeedback } from '../../services/feedback'
import type { FeedbackDraft } from '../../services/feedback'

export function FeedbackButton({ compact = false }: { compact?: boolean }) {
 const [open, setOpen] = useState(false)
 const [category, setCategory] = useState<FeedbackDraft['category']>('개선 제안')
 const [content, setContent] = useState('')
 const [status, setStatus] = useState('')
 const [busy, setBusy] = useState(false)
 const dialog = useRef<HTMLDialogElement>(null)
 const trigger = useRef<HTMLButtonElement>(null)
 const id = useId()
 useEffect(() => {
  if (!open) return
  dialog.current?.showModal()
  const previous = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  return () => { document.body.style.overflow = previous; trigger.current?.focus({ preventScroll:true }) }
 }, [open])
 async function copy() {
  if (busy) return
  if (!content.trim()) { setStatus('의견 내용을 입력해 주세요.'); return }
  setBusy(true)
  try { await copyFeedback({ category, content }); setStatus('의견을 복사했어요. 개발자에게 아직 전송되지는 않았어요.') }
  catch { setStatus('복사하지 못했어요. 내용을 직접 선택해 복사해 주세요.') }
  finally { setBusy(false) }
 }
 return <>
  <button ref={trigger} className={`p-feedback-button ${compact ? 'p-feedback-compact' : ''}`} aria-label="개발자에게 의견 주기" onClick={() => { setStatus(''); setOpen(true) }}>{compact ? '의견' : '개발자에게 의견 주기'}</button>
  {open && <dialog ref={dialog} className="p-feedback-dialog" aria-labelledby={`${id}-title`} onCancel={e => { e.preventDefault(); setOpen(false) }}>
   <div className="p-feedback-heading"><h2 id={`${id}-title`}>개발자에게 의견 주기</h2><button autoFocus onClick={() => setOpen(false)} aria-label="의견 창 닫기">×</button></div>
   <p className="p-feedback-notice">전송 기능은 준비 중이에요. 작성한 의견을 복사할 수 있어요. 개인정보는 적지 않아도 돼요.</p>
   <form onSubmit={e => { e.preventDefault(); void copy() }}>
    <label htmlFor={`${id}-type`}>의견 유형</label><select id={`${id}-type`} value={category} onChange={e => { setCategory(e.target.value as FeedbackDraft['category']); setStatus('') }}><option>버그 제보</option><option>개선 제안</option><option>기타</option></select>
    <label htmlFor={`${id}-content`}>의견 내용 <span>필수</span></label><textarea id={`${id}-content`} rows={6} maxLength={2000} value={content} onChange={e => { setContent(e.target.value); setStatus('') }} aria-describedby={`${id}-status`} placeholder="불편했던 점이나 아이디어를 알려 주세요." />
    <p id={`${id}-status`} className="p-feedback-status" role="status">{status}</p><button className="p-feedback-copy" type="submit" disabled={busy}>{busy ? '복사 중…' : '의견 복사'}</button>
   </form>
  </dialog>}
 </>
}
