import { useEffect, useRef, useState } from 'react'
import type { StoryProject } from '../../projects/stories/catalog'
import { mockStoryClient, storyClientMode } from '../../services/storyClient'
import { newRequestId } from '../../services/requestId'
import { clearProgress, saveProgress } from '../../services/storyProgress'
import type { StoryClient } from '../../services/storyClient'
import { StoryApiError, storyRetryPolicy } from '../../services/apiStoryClient'
import { crisisCareLine, isCrisisText } from '../../services/crisisSafety'
import type { CrisisProject } from '../../services/crisisSafety'

type TextMessage = { kind?: 'text'; situation?: string; role: 'user' | 'character'; speaker: string; text: string; reaction?: string; provider?: string; model?: string; dialogueProvider?: string }
export type StoryMessage = TextMessage | { kind: 'scene_image'; asset: string } | { kind: 'system'; text: string; label?: string } | { kind: 'crisis' }
export type StoryChatOptions = { startTurn?: number; resumed?: boolean; notice?: string }
export const RESUME_NOTICE = '지난 이야기에서 이어집니다. 이전 대화 내용은 이 기기에 저장하지 않아요.'
// 위기 신호: 안내 말풍선(CrisisNotice)과 캐릭터의 고정 곁말만 붙인다. 서버가 보낸 곁말이 있으면 그것을 쓴다.
function safetyMessages(projectId: string, reply?: { speaker: string; text: string }): StoryMessage[] {
  const care = reply?.text ? reply : crisisCareLine(projectId as CrisisProject)
  return [{ kind: 'crisis' }, { role: 'character', speaker: care.speaker, text: care.text }]
}
// resumed: 이어하기로 이 장면부터 시작하면, 새 표정이 아니어도(sceneImage 없음) 지금 장면의 표정(expression)을 한 번 보여 준다.
function opening(project: StoryProject, index: number, name?: string, resumed = false): StoryMessage[] {
 const found = project.steps[index]
 const step = resumed && !found.sceneImage && found.expression ? { ...found, sceneImage: found.expression } : found
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
export function useStoryChat(project: StoryProject, name: string, onResult: (ending?: string) => void, client: StoryClient = mockStoryClient, options: StoryChatOptions = {}) {
  // 마지막 장면 응답에 서버가 정한 결말 ID가 온다(API·서버 Mock 모드). 대화 중에는 호칭·단계를 바꾸지 않는다.
  const ending = useRef<string | undefined>(undefined)
  const startTurn = Math.min(Math.max(options.startTurn ?? 0, 0), project.steps.length - 1)
  const [turn, setTurn] = useState(startTurn)
  const [messages, setMessages] = useState<StoryMessage[]>(() => options.resumed
    ? [{ kind: 'system', label: '이어하기', text: RESUME_NOTICE }, ...opening(project, startTurn, startTurn === 0 ? name : undefined, true)]
    : [...(options.notice ? [{ kind: 'system' as const, label: '이어하기', text: options.notice }] : []), ...opening(project, 0, name)])
  // 진행 저장: 호칭과 완료한 장면 수, API 모드의 서버 대화 정보만 이 기기에 둔다(대화 원문 제외).
  const remember = (completedTurns: number) => saveProgress({ project: project.id, mode: storyClientMode(), name, completedTurns, api: client.session?.() ?? undefined })
  useEffect(() => { remember(startTurn) }, []) // eslint-disable-line react-hooks/exhaustive-deps
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
        if (reply.meta?.ending) ending.current = reply.meta.ending
        setErrorMessage(undefined); setStatus('replied')
        remember(turn + 1)
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
    if (next === project.steps.length) { clearProgress(project.id); onResult(ending.current); return }
    setTurn(next); setSelected(undefined); pending.current = null; setStatus('idle')
    setMessages(old => [...old, ...opening(project, next)])
  }
  return { turn, messages, status, selected, step, send, retry: run, advance, errorMessage, retryBlocked, retryWait, canRetry }
}
