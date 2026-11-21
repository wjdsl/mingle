// 개발용 응답 출처 추적. 화면의 대사가 Mock인지 실제 API인지(공급자·모델) 구분하기 위한 표시 전용이다.
// 대사 본문·호칭·개인 코드는 기록하지 않는다. 프로덕션 빌드에서는 로그와 배지를 내보내지 않는다.

type SourceDetails = { provider?: string; model?: string; dialogueProvider?: string; fallbackReason?: string }
export type SourceTrace = SourceDetails & { channel: 'puruma' | 'story'; mode: string; calls: number; lastError?: string }

export function isDevBuild(): boolean {
  return Boolean((import.meta as { env?: Record<string, unknown> }).env?.DEV)
}

export function createTrace(channel: SourceTrace['channel'], mode: string): SourceTrace {
  return { channel, mode, calls: 0 }
}

export function recordSource(trace: SourceTrace, { error, ...details }: SourceDetails & { error?: string }) {
  trace.calls += 1
  Object.assign(trace, details, { lastError: error })
  if (isDevBuild()) console.info(`[mingle:${trace.channel}] ${describeTrace(trace)}`)
}

export function describeTrace(trace: SourceTrace): string {
  const source = trace.mode === 'mock' || trace.mode === 'scenario-mock' ? `MOCK(${trace.mode})` : `API`
  const provider = trace.calls === 0 ? '응답 대기 전' : trace.lastError ? `오류: ${trace.lastError}` : `provider=${trace.provider ?? '?'}${trace.model ? ` model=${trace.model}` : ''}`
  const dialogue = !trace.lastError && trace.dialogueProvider && trace.dialogueProvider !== trace.provider
    ? ` · dialogue=${trace.dialogueProvider}` : ''
  const fallback = !trace.lastError && trace.fallbackReason ? ` · fallback=${trace.fallbackReason}` : ''
  return `${source} · ${provider}${dialogue}${fallback}`
}
