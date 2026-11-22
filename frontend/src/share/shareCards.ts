// 메신저 미리보기 카드(Open Graph·Twitter 카드) 정보와 작품별 공유 페이지 HTML (2026-11-22)
// - 메신저는 주소의 # 뒤를 읽지 않으므로 작품마다 /share/<작품ID>/ 정적 페이지를 만들고,
//   그 페이지가 메타 태그를 갖고 있다가 브라우저에서는 기존 작품 화면(#/project/<작품ID>)으로 넘긴다.
// - 링크에는 작품 ID와 공유 유입 표시(?from=share)만 넣는다. 호칭·대화·결과는 넣지 않는다.
// - vite.config.ts(빌드·개발 서버)와 shareProject.ts, 테스트가 함께 쓴다. 이미지·React를 import하지 않는다.
// - 문구 출처: 제목·소개는 catalog.ts의 title·description(테스트로 일치 확인), 사이트 카드는 홈 첫 문구.

export const SHARE_PROJECT_IDS = ['puruma', 'fridge', 'cloud'] as const
export type ShareProjectId = (typeof SHARE_PROJECT_IDS)[number]

// image: 배포 주소 기준 경로(public/og/). 1200×630 JPG.
export type ShareCard = { title: string; description: string; image: string; imageAlt: string }

export const SITE_CARD: ShareCard = {
  title: 'MINGLE · 이야기 속으로',
  description: '오늘은, 어떤 이야기의 주인공이 되어 볼까요? 캐릭터에게 말을 걸며 함께 이야기를 만들어 가요.',
  image: 'og/site.jpg',
  imageAlt: 'MINGLE의 세 작품, 푸르마와 학교 다니기·우리 집 냉장고가 재벌 회장님이다·구름섬 구조대',
}

export const PROJECT_CARDS: Record<ShareProjectId, ShareCard & { projectTitle: string }> = {
  puruma: {
    projectTitle: '푸르마와 학교 다니기',
    title: '푸르마와 학교 다니기 | MINGLE',
    description: '낯선 캠퍼스의 첫날. 조금 서툰 신입생 푸르마의 든든한 선배가 되어 주세요.',
    image: 'og/puruma.jpg',
    imageAlt: '손을 흔드는 신입생 푸르마',
  },
  fridge: {
    projectTitle: '우리 집 냉장고가 재벌 회장님이다',
    title: '우리 집 냉장고가 재벌 회장님이다 | MINGLE',
    description: '중고 냉장고를 샀을 뿐인데, 전직 재벌 회장과 동거를 시작했다. 전 재산은… 냉동 만두 한 봉지?',
    image: 'og/fridge.jpg',
    imageAlt: '원룸에서 자신만만한 표정을 짓는 냉장고 회장',
  },
  cloud: {
    projectTitle: '구름섬 구조대',
    title: '구름섬 구조대 | MINGLE',
    description: '하늘의 섬들이 떨어지기 시작했다! 다섯 대원과 힘을 모아 하늘의 균형을 되찾는 모험.',
    image: 'og/cloud.jpg',
    imageAlt: '구름 위에 떠 있는 하늘섬들과 출발을 기다리는 구조선',
  },
}

export const SHARE_QUERY = 'from=share'

export function isShareProjectId(id: string): id is ShareProjectId {
  return (SHARE_PROJECT_IDS as readonly string[]).includes(id)
}

// appBase: 앱이 열리는 주소(오리진 + 기본 경로, 예: https://example.com/ 또는 http://127.0.0.1:5173/).
export function projectShareUrl(appBase: string, projectId: string): string {
  const base = appBase.endsWith('/') ? appBase : `${appBase}/`
  return new URL(`share/${encodeURIComponent(projectId)}/?${SHARE_QUERY}`, base).href
}

// siteUrl: VITE_SITE_URL(배포 주소). 없으면 상대 경로를 그대로 둔다(메신저 카드 이미지는 표시되지 않을 수 있다).
export function absoluteUrl(siteUrl: string | undefined, path: string): string {
  if (!siteUrl) return `/${path.replace(/^\//, '')}`
  return new URL(path.replace(/^\//, ''), siteUrl.endsWith('/') ? siteUrl : `${siteUrl}/`).href
}

const escapeHtml = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

export function metaTags(card: ShareCard, pagePath: string, siteUrl: string | undefined): string {
  const image = absoluteUrl(siteUrl, card.image)
  const tags: [string, string, string][] = [
    ['name', 'description', card.description],
    ['property', 'og:type', 'website'],
    ['property', 'og:site_name', 'MINGLE'],
    ['property', 'og:locale', 'ko_KR'],
    ['property', 'og:title', card.title],
    ['property', 'og:description', card.description],
    ['property', 'og:image', image],
    ['property', 'og:image:width', '1200'],
    ['property', 'og:image:height', '630'],
    ['property', 'og:image:alt', card.imageAlt],
    ['name', 'twitter:card', 'summary_large_image'],
    ['name', 'twitter:title', card.title],
    ['name', 'twitter:description', card.description],
    ['name', 'twitter:image', image],
  ]
  if (siteUrl) tags.splice(4, 0, ['property', 'og:url', absoluteUrl(siteUrl, pagePath)])
  return tags.map(([attr, key, value]) => `<meta ${attr}="${key}" content="${escapeHtml(value)}" />`).join('\n    ')
}

// 작품별 공유 페이지. 메타 태그만 읽는 메신저용이며, 브라우저는 바로 작품 화면으로 넘어간다.
// 주소 뒤의 ?from=share를 그대로 넘겨 기존 공유 유입 통계(captureShareEntry)가 같은 방식으로 잡히게 한다.
export function renderSharePage(projectId: ShareProjectId, siteUrl: string | undefined): string {
  const card = PROJECT_CARDS[projectId]
  const target = `../../#/project/${projectId}`
  return `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml(card.title)}</title>
    ${metaTags(card, `share/${projectId}/`, siteUrl)}
    <script>location.replace('../../' + location.search + '#/project/${projectId}')</script>
  </head>
  <body>
    <p><a href="${target}">${escapeHtml(card.projectTitle)} 보러 가기</a></p>
  </body>
</html>
`
}
