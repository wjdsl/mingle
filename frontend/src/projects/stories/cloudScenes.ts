// 구름섬 장면 이미지 (2026-11-22 기획 결정)
// - 첫 임무를 시작하는 1턴에만 하늘섬 배경 이미지를 한 번 보여 준다. 같은 이미지를 홈 작품 카드 썸네일로도 쓴다.
// - API·서버 Mock 모드(scenario_draft_v1)와 브라우저 Mock(catalog.ts 첫 미션) 모두 1턴에 적용한다.
// - 이어하기로 2턴 이후부터 들어오면 다시 보여 주지 않는다(표정처럼 상태를 나타내는 이미지가 아니라 도입 장면이라서).
// 키: 0부터 세는 턴 번호(화면의 1턴 = 0).
export const CLOUD_SCENE_IMAGES: Readonly<Record<number, string>> = {
  0: 'cloud-sky-islands', // 1턴 첫 임무 · 섬이 흔들리기 시작한 하늘
}

export function cloudSceneImage(turn: number): string | undefined {
  return CLOUD_SCENE_IMAGES[turn]
}
