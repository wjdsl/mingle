// 세 작품 진행 저장·복원 (기획서 FR-04·FR-12, NFR-05·06). 푸르마는 2026-11-22부터 같은 형식을 쓴다.
// - 이 기기 브라우저(localStorage)에만 저장한다. 서버·통계로 보내지 않는다.
// - 대화 원문은 저장하지 않는다. 호칭, 완료한 장면 수, (API 모드) 서버 대화를 이어 갈 개인 코드·대화 ID만 둔다.
// - 실행 모드(mock / scenario-mock / api)가 다르면 다른 기록으로 본다. 장면 구성이 달라 섞이면 안 된다.
// - 저장소 접근이 막혀 있으면(비공개 모드 등) 저장 없이 동작하고 예외를 밖으로 던지지 않는다.
// - 보관 기간은 기획서 미결정 1번이라 만료를 두지 않았다.

export type StoryMode = 'mock' | 'scenario-mock' | 'api'
export type SavedProgress = {
  v: 1
  project: string
  mode: StoryMode
  name: string
  completedTurns: number
  api?: { code: string; conversationId: string }
  savedAt: number
}
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const key = (project: string) => `mingle.progress.v1.${project}`

function defaultStorage(): StorageLike | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}

function isSaved(value: unknown, project: string): value is SavedProgress {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  const api = v.api as Record<string, unknown> | undefined
  return v.v === 1 && v.project === project && (v.mode === 'mock' || v.mode === 'scenario-mock' || v.mode === 'api') &&
    typeof v.name === 'string' && Number.isInteger(v.completedTurns) && (v.completedTurns as number) >= 0 &&
    (api === undefined || (typeof api === 'object' && api !== null && typeof api.code === 'string' && typeof api.conversationId === 'string'))
}

export function loadProgress(project: string, mode: StoryMode, storage: StorageLike | null = defaultStorage()): SavedProgress | null {
  try {
    const raw = storage?.getItem(key(project))
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isSaved(parsed, project) || parsed.mode !== mode) return null
    return parsed
  } catch { return null }
}

export function saveProgress(progress: Omit<SavedProgress, 'v' | 'savedAt'>, storage: StorageLike | null = defaultStorage()) {
  try {
    const value: SavedProgress = { v: 1, savedAt: Date.now(), ...progress, name: Array.from(progress.name).slice(0, 12).join('') }
    storage?.setItem(key(progress.project), JSON.stringify(value))
  } catch { /* 저장 실패는 진행을 막지 않는다. */ }
}

export function clearProgress(project: string, storage: StorageLike | null = defaultStorage()) {
  try { storage?.removeItem(key(project)) } catch { /* 무시 */ }
}
