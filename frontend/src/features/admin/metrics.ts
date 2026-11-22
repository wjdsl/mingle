import { findEnding } from '../../services/endingCollection.ts'
import type { DataMode } from '../../services/adminClient.ts'

// 대시보드 표시용 보조 함수. 집계는 서버가 하고, 화면은 이름·단위만 붙인다.

export const DATA_MODES: { id: DataMode; label: string }[] = [
  { id: 'real', label: '실제 데이터' },
  { id: 'sample', label: '샘플 데이터' },
  { id: 'all', label: '전체(샘플 포함)' },
]

// 실제 데이터만 보는 화면이 아니면 "샘플 데이터" 표시를 붙인다(FR-73).
export const showsSample = (mode: DataMode) => mode !== 'real'

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60), rest = seconds % 60
  if (minutes < 60) return rest ? `${minutes}분 ${rest}초` : `${minutes}분`
  const hours = Math.floor(minutes / 60)
  return `${hours}시간 ${minutes % 60}분`
}

// 결말 이름은 결말 도감과 같은 목록(endingCollection)을 쓴다. 모르는 ID는 ID를 그대로 보여 준다.
export const endingTitle = (project: string, id: string) => findEnding(project, id)?.title ?? id

export const rateText = (rate: number | null) => rate === null ? '—' : `${rate}%`
