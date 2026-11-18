import { useEffect, useState } from 'react'
import { PENDING_MESSAGES, pendingLevel } from './pendingText.ts'
import type { PendingLevel } from './pendingText.ts'

// 응답을 기다리는 동안 표시한다. 마운트 시각부터 실제로 흐른 시간만 보고 문구를 바꾼다.
// 문구가 바뀔 때만 스크린 리더(role=status)에 전달되고, 점 애니메이션은 장식이라 숨긴다.
export function PendingNotice() {
  const [level, setLevel] = useState<PendingLevel>(0)
  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setLevel(pendingLevel(Date.now() - started)), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return <p className="typing" role="status"><span className="typing-dots" aria-hidden="true"><i>●</i><i>●</i><i>●</i></span> {PENDING_MESSAGES[level]}</p>
}
