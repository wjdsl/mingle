import { projectShareUrl } from '../share/shareCards.ts'

export async function shareProject(title: string, projectId: string): Promise<{ message: string; manualLink?: string }> {
  // 메신저 미리보기 카드가 있는 작품별 공유 페이지(/share/<작품ID>/?from=share). 열면 작품 소개 화면으로 넘어간다.
  // 호칭, 대화, 결과를 공유 URL에 포함하지 않는다.
  const href = projectShareUrl(new URL(import.meta.env.BASE_URL, window.location.origin).href, projectId)
  const data = { title, text: 'MINGLE에서 새로운 이야기를 만나 보세요.', url: href }
  try {
    if (navigator.share) { await navigator.share(data); return { message: '작품 링크를 공유했어요.' } }
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(href); return { message: '작품 소개 링크를 복사했어요.' } }
    return { message: '아래 작품 링크를 복사해 주세요.', manualLink: href }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return { message: '' }
    return { message: '공유를 완료하지 못했어요. 아래 링크를 복사해 주세요.', manualLink: href }
  }
}
