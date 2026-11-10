import { useEffect, useRef, useState } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import { requestStoryReply } from '../../services/mockStoryClient'

type TextMessage = { kind?: 'text'; situation?: string; role: 'user' | 'character'; speaker: string; text: string; reaction?: string }
export type StoryMessage = TextMessage | { kind: 'scene_image'; asset: string } | { kind: 'system'; text: string }
function opening(project: StoryProject, index: number, name?: string): StoryMessage[] {
 const step = project.steps[index]
 return [
  ...(step.sceneImage ? [{ kind: 'scene_image' as const, asset: step.sceneImage }] : []),
  ...(step.event ? [{ kind: 'system' as const, text: step.event }] : []),
  { kind: 'text', role: 'character', speaker: step.speaker, text: `${name ? name + ', ' : ''}${step.text}`, situation: step.situation }
 ]
}
export function useStoryChat(project: StoryProject, name: string, onResult: () => void) {
  const [turn, setTurn] = useState(0)
  const [messages, setMessages] = useState<StoryMessage[]>(() => opening(project, 0, name))
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'replied'>('idle')
  const [selected, setSelected] = useState<number>()
  const controller = useRef<AbortController | null>(null)
  const pending = useRef<{ text: string; choice?: number } | null>(null)
  const busy = useRef(false)
  const failedTurns = useRef(new Set<number>())
  const step = project.steps[turn]
  useEffect(() => () => controller.current?.abort(), [])
  async function run() {
    if (busy.current || !pending.current) return
    busy.current = true
    setStatus('loading')
    const abort = new AbortController()
    controller.current = abort
    const fail = new URLSearchParams(window.location.search).get('mockError') === 'once' && !failedTurns.current.has(turn)
    failedTurns.current.add(turn)
    try {
      const reply = await requestStoryReply(project, turn, pending.current.choice, abort.signal, fail)
      if (!abort.signal.aborted) { setMessages(old => [...old, { role: 'character', ...reply }]); setStatus('replied') }
    } catch { if (!abort.signal.aborted) setStatus('error') }
    finally { if (controller.current === abort) busy.current = false }
  }
  function send(text: string, choice?: number) {
    if (busy.current || status !== 'idle' || !text.trim()) return
    pending.current = { text, choice }; setSelected(choice)
    setMessages(old => [...old, { role: 'user', speaker: name, text }]); void run()
  }
  function advance() {
    if (status !== 'replied' || !pending.current) return
    const next = turn + 1
    if (next === project.steps.length) { onResult(); return }
    setTurn(next); setSelected(undefined); pending.current = null; setStatus('idle')
    setMessages(old => [...old, ...opening(project, next)])
  }
  return { turn, messages, status, selected, step, send, retry: run, advance }
}
