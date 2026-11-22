// 결과 카드 이미지 저장 (기획서 FR-41). 새 라이브러리 없이 canvas로 그려 PNG로 내려받는다.
// - 호칭 등 개인정보는 넣지 않는다. 고정 샘플 결과는 이미지에도 그 표시(label·note)를 남긴다(FR-73).
// - 이미지는 같은 출처의 앱 에셋만 쓰므로 canvas가 오염되지 않는다.

export type ResultCard = {
  projectTitle: string
  title: string
  text: string
  imageSrc: string
  label?: string
  note?: string
  colors: { bg: string; surface: string; ink: string; accent: string }
  font: string
}

// 한국어는 띄어쓰기가 적어도 줄을 나눠야 하므로 글자 단위로 넓이를 재며 자른다. 테스트를 위해 measure를 주입한다.
export function wrapText(text: string, maxWidth: number, measure: (s: string) => number, maxLines = Infinity): string[] {
  const lines: string[] = []
  for (const paragraph of text.split('\n')) {
    let line = ''
    for (const char of Array.from(paragraph)) {
      if (line && measure(line + char) > maxWidth) {
        const space = line.lastIndexOf(' ')
        if (space > 0 && char !== ' ') { lines.push(line.slice(0, space)); line = line.slice(space + 1) + char }
        else { lines.push(line.trimEnd()); line = char === ' ' ? '' : char }
      } else line += char
    }
    lines.push(line)
  }
  if (lines.length <= maxLines) return lines
  const kept = lines.slice(0, maxLines)
  kept[maxLines - 1] = kept[maxLines - 1].replace(/.{0,1}$/u, '…')
  return kept
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('image'))
    img.src = src
  })
}

export async function renderResultImage(card: ResultCard): Promise<Blob> {
  const W = 1080, H = 1350, pad = 80
  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas')
  try { await document.fonts?.ready } catch { /* 시스템 서체로 그린다 */ }

  ctx.fillStyle = card.colors.bg; ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = card.colors.surface
  ctx.beginPath(); ctx.roundRect(pad / 2, pad / 2, W - pad, H - pad, 36); ctx.fill()

  let y = pad + 20
  ctx.fillStyle = card.colors.accent; ctx.font = `700 30px ${card.font}`; ctx.textBaseline = 'top'
  ctx.fillText(card.projectTitle, pad, y)
  if (card.label) {
    const w = ctx.measureText(card.label).width + 32
    ctx.fillStyle = card.colors.accent; ctx.beginPath(); ctx.roundRect(W - pad - w, y - 8, w, 48, 24); ctx.fill()
    ctx.fillStyle = card.colors.surface; ctx.fillText(card.label, W - pad - w + 16, y)
  }
  y += 70

  const img = await loadImage(card.imageSrc)
  const boxW = W - pad * 2, boxH = 600
  const scale = Math.min(boxW / img.width, boxH / img.height)
  const iw = img.width * scale, ih = img.height * scale
  ctx.drawImage(img, (W - iw) / 2, y + (boxH - ih) / 2, iw, ih)
  y += boxH + 40

  ctx.fillStyle = card.colors.ink; ctx.font = `800 56px ${card.font}`
  for (const line of wrapText(card.title, boxW, s => ctx.measureText(s).width, 2)) { ctx.fillText(line, pad, y); y += 70 }
  y += 10
  ctx.font = `400 32px ${card.font}`
  const bodyLines = card.note ? 4 : 6
  for (const line of wrapText(card.text, boxW, s => ctx.measureText(s).width, bodyLines)) { ctx.fillText(line, pad, y); y += 48 }
  if (card.note) {
    ctx.fillStyle = card.colors.accent; ctx.font = `600 26px ${card.font}`
    for (const line of wrapText(card.note, boxW, s => ctx.measureText(s).width, 2)) { ctx.fillText(line, pad, y + 10); y += 38 }
  }

  ctx.fillStyle = card.colors.ink; ctx.globalAlpha = 0.55; ctx.font = `700 28px ${card.font}`; ctx.textBaseline = 'bottom'
  ctx.fillText('mingle ✳', pad, H - pad + 10)
  ctx.globalAlpha = 1

  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('blob')), 'image/png'))
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.rel = 'noopener'
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

// ── 화면에 보이는 카드(DOM)를 그대로 PNG로 옮기는 저장(푸르마 졸업 카드·엔딩 도감용, #16) ──
// 호칭 등 카드에 표시된 내용은 사용자 기기의 파일에만 들어가며 서버로 보내지 않는다.

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = []
  for (const paragraph of text.split('\n')) {
    let current = ''
    for (const word of paragraph.split(/(\s+)/)) {
      const chars = ctx.measureText(current + word).width <= width ? [word] : Array.from(word)
      for (const piece of chars) {
        if (current && ctx.measureText(current + piece).width > width) { lines.push(current.trimEnd()); current = piece.trimStart() }
        else current += piece
      }
    }
    lines.push(current.trimEnd())
  }
  return lines
}

export function drawCard(card: HTMLElement, scale = 2): Promise<HTMLCanvasElement> {
  const box = card.getBoundingClientRect()
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(box.width * scale); canvas.height = Math.round(box.height * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) return Promise.reject(new Error('canvas unavailable'))
  ctx.scale(scale, scale)
  const style = getComputedStyle(card)
  ctx.fillStyle = style.backgroundColor === 'rgba(0, 0, 0, 0)' ? '#ffffff' : style.backgroundColor
  ctx.fillRect(0, 0, box.width, box.height)
  if (parseFloat(style.borderTopWidth) > 0) { ctx.strokeStyle = style.borderTopColor; ctx.lineWidth = 1; ctx.strokeRect(0.5, 0.5, box.width - 1, box.height - 1) }

  const loads: Promise<void>[] = []
  for (const element of card.querySelectorAll<HTMLElement>('*')) {
    const rect = element.getBoundingClientRect()
    if (!rect.width || !rect.height) continue
    const x = rect.left - box.left, y = rect.top - box.top
    const css = getComputedStyle(element)
    if (css.visibility === 'hidden' || css.display === 'none') continue
    if (element instanceof HTMLImageElement) {
      const image = element
      loads.push((async () => { try { await image.decode() } catch { return } ctx.drawImage(image, x, y, rect.width, rect.height) })())
      continue
    }
    const ownText = Array.from(element.childNodes).filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent ?? '').join('').trim()
    if (!ownText) continue
    ctx.font = `${css.fontStyle} ${css.fontWeight} ${css.fontSize} ${css.fontFamily}`
    ctx.fillStyle = css.color; ctx.textBaseline = 'top'
    const align = css.textAlign === 'center' ? 'center' : css.textAlign === 'right' || css.textAlign === 'end' ? 'right' : 'left'
    ctx.textAlign = align
    const lineHeight = parseFloat(css.lineHeight) || parseFloat(css.fontSize) * 1.5
    const left = align === 'center' ? x + rect.width / 2 : align === 'right' ? x + rect.width : x
    wrap(ctx, ownText, rect.width).forEach((line, index) => ctx.fillText(line, left, y + index * lineHeight + (lineHeight - parseFloat(css.fontSize)) / 2))
  }
  return Promise.all(loads).then(() => canvas)
}

export async function saveResultImage(card: HTMLElement, filename: string): Promise<void> {
  const canvas = await drawCard(card)
  const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
  if (!blob) throw new Error('image export failed')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename
  document.body.append(link); link.click(); link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
