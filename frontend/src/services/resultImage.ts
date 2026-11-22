// 결과 카드(DOM)를 PNG로 그려 저장한다. 외부 패키지 없이 화면에 보이는 카드의 이미지·텍스트·배경을 캔버스에 옮긴다.
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
