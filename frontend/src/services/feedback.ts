export type FeedbackDraft = { category: '버그 제보' | '개선 제안' | '기타'; content: string }
// 저장 API 계약이 아직 없으므로 네트워크 전송/성공을 흉내 내지 않는다.
export async function copyFeedback(draft: FeedbackDraft): Promise<void> {
 if (!draft.content.trim()) throw new Error('의견 내용을 입력해 주세요.')
 if (!navigator.clipboard) throw new Error('자동 복사를 지원하지 않아요. 작성한 내용을 직접 선택해서 복사해 주세요.')
 await navigator.clipboard.writeText(`[${draft.category}]\n${draft.content.trim()}`)
}
