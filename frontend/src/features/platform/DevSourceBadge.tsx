import { describeTrace, isDevBuild } from '../../services/devSource'
import type { SourceTrace } from '../../services/devSource'

// 개발 빌드 전용: 지금 대사가 Mock인지 실제 API(공급자·모델)인지 보여 준다. 프로덕션에서는 렌더하지 않는다.
export function DevSourceBadge({ trace }: { trace: SourceTrace }) {
  if (!isDevBuild()) return null
  return <p className="dev-source-badge" data-mode={trace.mode} role="note">DEV · {describeTrace(trace)}</p>
}
