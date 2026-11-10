import { useEffect, useRef, useState } from 'react'
import smug from '../../assets/fridge/fridge-smug.webp'
import angry from '../../assets/fridge/fridge-angry.webp'
import flustered from '../../assets/fridge/fridge-flustered.webp'
import office from '../../assets/fridge/chairman-office.webp'

export const sceneAssets: Record<string, { src: string; alt: string; caption: string }> = {
 'fridge-smug': { src: smug, alt: '작은 원룸에서 자신만만한 표정을 띤 냉장고 회장', caption: '원룸의 냉장고 회장' },
 'fridge-angry': { src: angry, alt: '원룸에서 붉게 화난 표정을 표시하는 냉장고', caption: '회장의 디스플레이가 붉어진다' },
 'fridge-flustered': { src: flustered, alt: '원룸에서 당황한 표정을 짓는 냉장고 회장', caption: '흠흠… 당황한 회장님' },
 'chairman-office': { src: office, alt: '넓은 사무실에서 정장을 입고 앉아 있는 회장', caption: '회장이 주장하는 과거 · 회상 이미지' },
}
export function SceneImage({ asset }: { asset: string }) {
 const image = sceneAssets[asset]
 const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
 const [attempt, setAttempt] = useState(0)
 const [open, setOpen] = useState(false)
 const dialog = useRef<HTMLDialogElement>(null)
 const trigger = useRef<HTMLButtonElement>(null)
 useEffect(() => { if (open) { dialog.current?.showModal(); const previous = document.body.style.overflow; document.body.style.overflow = 'hidden'; return () => { document.body.style.overflow = previous; trigger.current?.focus({ preventScroll: true }) } } }, [open])
 if (!image) return null
 return <figure className="p-scene-image">
  {state === 'loading' && <span role="status">장면을 불러오는 중…</span>}
  {state === 'error' ? <div role="alert">이미지를 불러오지 못했어요.<button onClick={() => { setState('loading'); setAttempt(a => a + 1) }}>다시 불러오기</button></div> : <button ref={trigger} className="p-image-trigger" disabled={state !== 'ready'} onClick={() => setOpen(true)} aria-label={`${image.caption} 확대 보기`}><img key={attempt} src={image.src} alt={image.alt} onLoad={() => setState('ready')} onError={() => setState('error')} /></button>}
  <figcaption>{image.caption}{state === 'ready' && ' · 눌러서 확대'}</figcaption>
  {open && <dialog ref={dialog} className="p-image-dialog" aria-label="장면 이미지 확대" onCancel={e => { e.preventDefault(); setOpen(false) }} onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}><header className="p-image-dialog-header"><p>{image.caption}</p><button autoFocus onClick={() => setOpen(false)} aria-label="확대 이미지 닫기">×</button></header><img src={image.src} alt={image.alt} /></dialog>}
 </figure>
}
