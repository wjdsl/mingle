// 냉장고 서버 장면 세트(scenario_draft_v1, API·서버 Mock 모드)의 회장 표정 이미지 (2026-11-22 기획 결정)
// - 매 턴이 아니라 이야기 구간이 시작되는 4개 턴에만 넣는다(도입·전개 끝·위기·예고편).
// - 확정 원화가 아니라 GitHub에 있는 표정 이미지 3장(자신만만·화남·당황)을 썼다. 근거는 장면 카드 첫 대사의 지문과 장면 분위기.
// - 이어하기로 이미지가 없는 턴부터 들어오면, 그 앞에서 마지막으로 나온 표정을 한 번 보여 준다.
// - 회장 사무실(chairman-office)은 명시적 회상 장면에만 쓰는 원칙이라 쓰지 않는다.
// 키: 0부터 세는 턴 번호(화면의 1턴 = 0).
export const FRIDGE_SCENE_IMAGES: Readonly<Record<number, string>> = {
  0: 'fridge-angry', //     1턴 설치 첫날 밤 · 지문 "불만 가득한 눈썹"
  5: 'fridge-flustered', // 6턴 조금 가까워진 저녁 · 챙겨 주고 쑥스러워함
  6: 'fridge-angry', //     7턴 반품 요청 · 지문 "온도 -3℃ → -5℃", 위기 시작
  9: 'fridge-smug', //      10턴 돌아갈 방법 · 지문 "환하게 켜지는 눈"
}

// 장면에 들어갈 때 붙일 이미지(위 4개 턴만).
export function fridgeSceneImage(turn: number): string | undefined {
  return FRIDGE_SCENE_IMAGES[turn]
}

// 이 장면 시점의 표정: 이 턴까지 마지막으로 나온 이미지(이어하기용).
export function fridgeExpression(turn: number): string | undefined {
  for (let t = turn; t >= 0; t--) if (FRIDGE_SCENE_IMAGES[t]) return FRIDGE_SCENE_IMAGES[t]
  return undefined
}
