// 냉장고·구름섬 결말 도감 (기획서 FR-44·45)
// - 얻은 결말 ID만 이 기기 브라우저에 저장한다. 다시 시작해도 지우지 않는다.
// - 결말 판정(냉장고 관계 단계, 구름섬 성향 판정)은 아직 없어 recordEnding을 부르는 곳이 없다.
//   판정이 구현되면 결과가 정해지는 곳에서 recordEnding(project, id)만 부르면 된다.
//   고정 샘플·Mock 결과를 실제로 얻은 결말처럼 기록하지 않는다(기획서 FR-73).
// - 결말 목록 출처: data/fridge_data/rules/fridge_relationship_rules.json(stages),
//   data/cloud_data/ending/cloud_result_types.json(result_cards). 둘 다 '가안'이다.

export type Ending = { id: string; title: string }

export const ENDINGS: Record<'fridge' | 'cloud', Ending[]> = {
  fridge: [
    { id: 'fridge_rel_stage_1', title: '고장 난 가전과 주인' },
    { id: 'fridge_rel_stage_2', title: '동거인' },
    { id: 'fridge_rel_stage_3', title: '동업자' },
  ],
  cloud: [
    { id: 'cloud_result_toto', title: '앞장서는 돌격 대장형' },
    { id: 'cloud_result_bibi', title: '빈틈없는 설계자형' },
    { id: 'cloud_result_nana', title: '모두를 지키는 등불형' },
    { id: 'cloud_result_kiki', title: '반짝이는 모험 친구형' },
    { id: 'cloud_result_dudu', title: '묵묵한 버팀목형' },
  ],
}

export type CollectionProject = keyof typeof ENDINGS
export function hasCollection(project: string): project is CollectionProject { return project in ENDINGS }

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>
const KEY = 'mingle.endings.v1'

function defaultStorage(): StorageLike | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}

function readAll(storage: StorageLike | null): Record<string, string[]> {
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(KEY) ?? '{}')
    return typeof parsed === 'object' && parsed !== null ? parsed as Record<string, string[]> : {}
  } catch { return {} }
}

export function loadAcquired(project: CollectionProject, storage: StorageLike | null = defaultStorage()): string[] {
  const known = new Set(ENDINGS[project].map(e => e.id))
  const saved = readAll(storage)[project]
  return Array.isArray(saved) ? ENDINGS[project].map(e => e.id).filter(id => known.has(id) && saved.includes(id)) : []
}

export function recordEnding(project: CollectionProject, endingId: string, storage: StorageLike | null = defaultStorage()): boolean {
  if (!ENDINGS[project].some(e => e.id === endingId)) return false
  try {
    const all = readAll(storage)
    const current = Array.isArray(all[project]) ? all[project] : []
    if (!current.includes(endingId)) storage?.setItem(KEY, JSON.stringify({ ...all, [project]: [...current, endingId] }))
    return true
  } catch { return false }
}
