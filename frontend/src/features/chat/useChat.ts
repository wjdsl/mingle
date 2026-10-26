import { useEffect, useReducer, useRef, useState } from 'react'
import { chatReducer, initialState, validateInput } from './chatReducer'
import { mockConversationClient } from '../../services/mockConversationClient'
import type { ConversationClient, TurnInput, TurnRequest } from './types'

export function useChat(client: ConversationClient = mockConversationClient) {
  const [state, dispatch] = useReducer(chatReducer, undefined, initialState)
  const [draft, setDraft] = useState('')
  const [validation, setValidation] = useState<string | null>(null)
  const inFlight = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  async function run(request: TurnRequest) {
    const abort = new AbortController()
    controller.current = abort
    try {
      const response = await client.sendTurn(request, abort.signal)
      if (!abort.signal.aborted) dispatch({ type: 'success', requestId: request.requestId, response })
    } catch {
      if (!abort.signal.aborted) dispatch({ type: 'failure', requestId: request.requestId })
    } finally { if (controller.current === abort) inFlight.current = false }
  }
  function send(input: TurnInput) {
    if (inFlight.current || state.status !== 'idle') return
    const error = validateInput(input.text)
    setValidation(error)
    if (error) return
    const request: TurnRequest = { requestId: crypto.randomUUID(), turn: state.completedTurns + 1, input: { ...input, text: input.text.trim() } }
    inFlight.current = true
    dispatch({ type: 'send', request })
    setDraft('')
    void run(request)
  }
  function retry() {
    if (inFlight.current || state.status !== 'error' || !state.pending) return
    inFlight.current = true
    dispatch({ type: 'retry' })
    void run(state.pending)
  }
  function reset() {
    controller.current?.abort()
    inFlight.current = false
    dispatch({ type: 'reset' }); setDraft(''); setValidation(null)
  }
  return { state, draft, setDraft, validation, send, retry, reset }
}
