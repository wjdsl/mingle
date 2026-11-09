import type { StoryProject } from '../projects/stories/catalog'

export type StoryReply = { speaker: string; text: string; reaction: string }
// 신규 작품 전용 Mock. 실제 API 계약이나 AI 분석을 구현하지 않는다.
export async function requestStoryReply(project: StoryProject, turn: number, choice: number | undefined, signal: AbortSignal, fail = false): Promise<StoryReply> {
  await new Promise<void>((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return }
    const timer = globalThis.setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 650)
    function abort() { globalThis.clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    signal.addEventListener('abort', abort, { once: true })
  })
  if (fail) throw new Error('Mock 응답 실패')
  const step = project.steps[turn]
  if (!step) throw new Error('존재하지 않는 시연 구간')
  const selected = choice === undefined ? undefined : step.choices[choice]
  const text = selected?.reply ?? step.reply
  const speaker = project.characters.find(character => text.startsWith(`${character.name}: `))?.name ?? step.speaker
  return { speaker, text: text.startsWith(`${speaker}: `) ? text.slice(speaker.length + 2) : text, reaction: selected?.reaction ?? '이야기가 이어져요' }
}
