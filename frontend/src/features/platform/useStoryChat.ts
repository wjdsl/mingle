import { useEffect, useRef, useState } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import { mockStoryClient } from '../../services/storyClient'
import { newRequestId } from '../../services/requestId'
import type { StoryClient } from '../../services/storyClient'
import { StoryApiError, storyRetryPolicy } from '../../services/apiStoryClient'
import { crisisCareLine, isCrisisText } from '../../services/crisisSafety'
import type { CrisisProject } from '../../services/crisisSafety'

type TextMessage = { kind?: 'text'; situation?: string; role: 'user' | 'character'; speaker: string; text: string; reaction?: string; provider?: string; model?: string; dialogueProvider?: string }
export type StoryMessage = TextMessage | { kind: 'scene_image'; asset: string } | { kind: 'system'; text: string } | { kind: 'crisis' }
// 위기 신호: 안내 말풍선(CrisisNotice)과 캐릭터의 고정 곁말만 붙인다. 서버가 보낸 곁말이 있으면 그것을 쓴다.
function safetyMessages(projectId: string, reply?: { speaker: string; text: string }): StoryMessage[] {
  const care = reply?.text ? reply : crisisCareLine(projectId as CrisisProject)
  return [{ kind: 'crisis' }, { role: 'character', speaker: care.speaker, text: care.text }]
}
function opening(project: StoryProject, index: number, name?: string): StoryMessage[] {
 const step = project.steps[index]
 if (step.openingLines) {
   return [
     ...(step.sceneImage ? [{ kind: 'scene_image' as const, asset: step.sceneImage }] : []),
     ...(step.systemMessages ?? []).map(text => ({ kind: 'system' as const, text })),
     ...step.openingLines.map((line, i): StoryMessage => ({ role: 'character', ...line, situation: i === 0 ? step.situation : undefined })),
     ...(!step.openingLines.length && step.situation ? [{ kind: 'system' as const, text: step.situation }] : []),
   ]
 }
 return [
  ...(step.sceneImage ? [{ kind: 'scene_image' as const, asset: step.sceneImage }] : []),
  ...(step.event ? [{ kind: 'system' as const, text: step.event }] : []),
  { kind: 'text', role: 'character', speaker: step.speaker, text: `${name ? name + ', ' : ''}${step.text}`, situation: step.situation }
 ]
}
export function useStoryChat(project: StoryProject, name: string, onResult: () => void, client: StoryClient = mockStoryClient) {
  const [turn, setTurn] = useState(0)
  const [messages, setMessages] = useState<StoryMessage[]>(() => opening(project, 0, name))
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'replied'>('idle')
  const [selected, setSelected] = useState<number>()
  const [errorMessage, setErrorMessage] = useState<string>()
  const [retryBlocked, setRetryBlocked] = useState(false)
  const [retryWait, setRetryWait] = useState(0)
  const [canRetry, setCanRetry] = useState(true)
  const controller = useRef<AbortController | null>(null)
  const pending = useRef<{ requestId: string; text: string; choice?: number } | null>(null)
  const busy = useRef(false)
  const failedTurns = useRef(new Set<number>())
  const step = project.steps[turn]
  const retryTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  useEffect(() => () => {
    controller.current?.abort()
    clearInterval(retryTimer.current)
  }, [])
  async function run() {
    if (busy.current || retryBlocked || !canRetry || !pending.current) return
    busy.current = true
    setStatus('loading')
    const abort = new AbortController()
    controller.current = abort
    const fail = new URLSearchParams(window.location.search).get('mockError') === 'once' && !failedTurns.current.has(turn)
    failedTurns.current.add(turn)
    try {
      const reply = await client.sendTurn({ requestId: pending.current.requestId, project, turn, input: { text: pending.current.text, choice: pending.current.choice }, mockFailure: fail }, abort.signal)
      if (!abort.signal.aborted && reply.safety) {
        // 서버가 위기 신호로 판단한 경우: 장면은 진행하지 않는다. 안내와 곁말만 보여 주고 같은 장면에서 이어 입력한다.
        setMessages(old => [...old, ...safetyMessages(project.id, reply)])
        pending.current = null; setSelected(undefined); setErrorMessage(undefined); setStatus('idle')
      } else if (!abort.signal.aborted) {
        // 실제 API는 구름섬에서 여러 대원의 대사를 돌려줄 수 있다. 반응 표시는 마지막 말풍선에 둔다.
        const lines = [{ speaker: reply.speaker, text: reply.text }, ...(reply.followUps ?? [])]
        const meta = reply.meta ? { provider: reply.meta.provider, model: reply.meta.model, dialogueProvider: reply.meta.dialogueProvider } : {}
        setMessages(old => [...old, ...lines.map((line, i): StoryMessage => ({ role: 'character', ...line, ...meta, ...(i === lines.length - 1 ? { reaction: reply.reaction } : {}) }))])
        setErrorMessage(undefined); setStatus('replied')
      }
    } catch (error) {
      if (!abort.signal.aborted) {
        setErrorMessage(error instanceof StoryApiError ? error.message : undefined)
        setStatus('error')
        // 대기 중에는 버튼을 잠그고 남은 초를 보여 준다. 재시도해도 해결되지 않는 오류는 버튼을 숨긴다.
        // 재시도는 pending.current의 같은 requestId를 다시 보내므로 서버에 같은 턴이 두 번 저장되지 않는다.
        const policy = storyRetryPolicy(error)
        setCanRetry(policy.canRetry)
        if (policy.canRetry && policy.waitSeconds > 0) {
          const until = Date.now() + policy.waitSeconds * 1000
          setRetryBlocked(true); setRetryWait(policy.waitSeconds)
          clearInterval(retryTimer.current)
          retryTimer.current = setInterval(() => {
            const left = Math.ceil((until - Date.now()) / 1000)
            if (left > 0) { setRetryWait(left); return }
            clearInterval(retryTimer.current); setRetryWait(0); setRetryBlocked(false)
          }, 250)
        }
      }
    }
    finally { if (controller.current === abort) busy.current = false }
  }
  function send(text: string, choice?: number) {
    if (busy.current || status !== 'idle' || (step.inputMode !== 'none' && !text.trim())) return
    // 위기 신호(자유 입력만): 서버·LLM에 보내지 않고 바로 안내한다. 입력은 이 화면의 메모리에만 있다. 장면은 진행하지 않는다.
    if (choice === undefined && step.inputMode !== 'none' && isCrisisText(text)) {
      setSelected(undefined)
      setMessages(old => [...old, { role: 'user', speaker: name, text }, ...safetyMessages(project.id)])
      return
    }
    pending.current = { requestId: newRequestId(), text, choice }; setSelected(choice)
    if (step.inputMode !== 'none') setMessages(old => [...old, { role: 'user', speaker: name, text }])
    void run()
  }
  function advance() {
    if (status !== 'replied' || !pending.current) return
    const next = turn + 1
    if (next === project.steps.length) { onResult(); return }
    setTurn(next); setSelected(undefined); pending.current = null; setStatus('idle')
    setMessages(old => [...old, ...opening(project, next)])
  }
  return { turn, messages, status, selected, step, send, retry: run, advance, errorMessage, retryBlocked, retryWait, canRetry }
}
