// 푸르마 기억(UserNote)의 브라우저 로컬 저장소.
// - 저장 대상은 서버가 돌려준 기억 목록(최대 10개)뿐이다. 대화 원문·개인 코드·대화 ID는 저장하지 않는다.
// - 서버 응답의 notes를 정본으로 덮어쓴다. 기억 추출·중요도 판정은 서버 정책이며 여기서 하지 않는다.
// - localStorage 접근이 막혀 있으면(비공개 모드 등) 이 탭의 메모리로만 동작한다. 예외는 밖으로 던지지 않는다.
// - 서버가 매 요청마다 다시 검증하므로 여기서는 형태만 확인한다.

export const USER_NOTE_STORAGE_KEY = 'mingle:puruma:usernotes:v1'
export const MAX_USER_NOTES = 10

export type UserNote = {
  key: string
  field: string
  value: string
  importance: string
  created_at_turn: number
  updated_at_turn: number
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function isTurn(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100000
}

export function normalizeNotes(value: unknown): UserNote[] {
  if (!Array.isArray(value)) return []
  const notes: UserNote[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const note = item as Record<string, unknown>
    if (typeof note.key !== 'string' || !note.key || note.key.length > 120) continue
    if (typeof note.field !== 'string' || !note.field || note.field.length > 40) continue
    if (typeof note.value !== 'string' || !note.value || note.value.length > 200) continue
    if (typeof note.importance !== 'string' || !note.importance || note.importance.length > 10) continue
    notes.push({
      key: note.key, field: note.field, value: note.value, importance: note.importance,
      created_at_turn: isTurn(note.created_at_turn) ? note.created_at_turn : 0,
      updated_at_turn: isTurn(note.updated_at_turn) ? note.updated_at_turn : 0,
    })
    if (notes.length >= MAX_USER_NOTES) break
  }
  return notes
}

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch { return null }
}

export function createUserNoteStore(getStorage: () => StorageLike | null = browserStorage) {
  let memory: UserNote[] | null = null // 저장소를 쓸 수 없을 때의 대체 보관(이 탭 안에서만)
  let epoch = 0 // 삭제할 때마다 증가: 삭제 전에 보낸 요청의 응답이 기억을 되살리지 못하게 한다.
  function read(): UserNote[] {
    if (memory) return memory
    try {
      const raw = getStorage()?.getItem(USER_NOTE_STORAGE_KEY)
      if (!raw) return []
      const data = JSON.parse(raw) as { version?: unknown; notes?: unknown }
      return data && data.version === 1 ? normalizeNotes(data.notes) : []
    } catch { return [] }
  }
  function write(notes: unknown): UserNote[] {
    const clean = normalizeNotes(notes)
    try {
      const storage = getStorage()
      if (!storage) throw new Error('storage unavailable')
      storage.setItem(USER_NOTE_STORAGE_KEY, JSON.stringify({ version: 1, notes: clean }))
      memory = null
    } catch { memory = clean }
    return clean
  }
  function clear(): void {
    epoch += 1
    write([]) // 키를 지우지 않고 빈 목록을 저장해 다음 요청이 항상 notes: []로 전송되게 한다.
  }
  return { read, write, clear, getEpoch: () => epoch }
}

export type UserNoteStore = ReturnType<typeof createUserNoteStore>
export const userNoteStore: UserNoteStore = createUserNoteStore()
