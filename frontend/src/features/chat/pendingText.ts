// 응답 대기 문구. 실제 경과 시간만으로 단계를 정하며 진행률·예상 완료 시간은 만들지 않는다.
export const PENDING_SLOW_MS = 8_000
export const PENDING_VERY_SLOW_MS = 20_000

export type PendingLevel = 0 | 1 | 2
export const PENDING_MESSAGES: Record<PendingLevel, string> = {
  0: '푸르마가 생각하고 있어요',
  1: '평소보다 시간이 걸리고 있어요. 답변을 기다리는 중이에요.',
  2: '아직 답변을 기다리고 있어요. 연결 상태에 따라 시간이 더 걸릴 수 있어요.',
}

export function pendingLevel(elapsedMs: number): PendingLevel {
  if (elapsedMs >= PENDING_VERY_SLOW_MS) return 2
  if (elapsedMs >= PENDING_SLOW_MS) return 1
  return 0
}
