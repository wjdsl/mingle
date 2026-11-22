import { PURUMA_ENDINGS } from '../projects/puruma/scenes.ts'

// 냉장고·구름섬 결말 도감 (기획서 FR-44·45)
// - 얻은 결말 ID만 이 기기 브라우저에 저장한다. 다시 시작해도 지우지 않는다.
// - 결말은 서버가 마지막 장면에서 정한다(API·서버 Mock 모드, 2026-11-22 기획 결정). Platform이 결과 화면으로 갈 때
//   recordEnding을 부른다. 판정이 없는 브라우저 Mock 모드의 고정 샘플은 획득으로 기록하지 않는다(기획서 FR-73).
// - 결말 목록 출처: data/fridge_data/rules/fridge_relationship_rules.json(stages),
//   data/cloud_data/ending/cloud_result_types.json(result_cards). 둘 다 '가안'이다.

// description: 구름섬은 cloud_result_types.json의 결과 카드 문구(가안) 그대로, 냉장고는 관계 단계 태도(tone)를 문장으로 옮겼다.
// character: 결과 카드에 보여 줄 캐릭터(구름섬 대원 이름). address: 회장이 부르는 말({{user}}는 화면에서 채운다).
export type Ending = { id: string; title: string; description: string; character?: string; address?: string }

// 푸르마: 시연용 엔딩 6종(기획서 6.1 문구). 서버 Mock·API 모드에서 서버가 10턴 끝에 정한 엔딩만 기록한다.
export const ENDINGS: Record<'fridge' | 'cloud' | 'puruma', Ending[]> = {
  puruma: PURUMA_ENDINGS.map(({ id, title, description }) => ({ id, title, description })),
  fridge: [
    { id: 'fridge_rel_stage_1', title: '고장 난 가전과 주인', address: '자네', description: '회장님은 여전히 거만하고 지시조예요. 아직은 당신을 믿지 않아요.' },
    { id: 'fridge_rel_stage_2', title: '동거인', address: '{{user}} 사원', description: '회장님은 투덜대면서도 조언을 건네요. 고마운 마음은 숨긴 채로요.' },
    { id: 'fridge_rel_stage_3', title: '동업자', address: '{{user}} 비서실장', description: '회장님이 당신을 믿고 사정을 조금 털어놓기 시작했어요. 자존심만큼은 여전하지만요.' },
  ],
  cloud: [
    { id: 'cloud_result_toto', title: '앞장서는 돌격 대장형', character: '토토', description: "망설이는 순간에도 먼저 한 발 내딛는 당신. 당신의 '가자!' 한마디가 모두에게 용기가 돼요." },
    { id: 'cloud_result_bibi', title: '빈틈없는 설계자형', character: '비비', description: '모두가 서두를 때 한 번 더 확인하는 당신. 당신 덕분에 오늘도 모두 무사해요.' },
    { id: 'cloud_result_nana', title: '모두를 지키는 등불형', character: '나나', description: '누군가의 떨리는 목소리를 가장 먼저 알아채는 당신. 당신 곁에서는 누구도 혼자가 아니에요.' },
    { id: 'cloud_result_kiki', title: '반짝이는 모험 친구형', character: '키키', description: '계획보다 마음이 먼저 움직이는 당신. 당신이 뛰어들면 모두가 따라 웃게 돼요.' },
    { id: 'cloud_result_dudu', title: '묵묵한 버팀목형', character: '두두', description: '말보다 행동으로 보여 주는 당신. 흔들리는 순간, 모두가 당신을 찾아요.' },
  ],
}

export function findEnding(project: string, endingId: string | null | undefined): Ending | undefined {
  return hasCollection(project) ? ENDINGS[project].find(e => e.id === endingId) : undefined
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
