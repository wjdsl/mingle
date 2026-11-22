import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { SHARE_PROJECT_IDS, SITE_CARD, isShareProjectId, metaTags, renderSharePage } from './src/share/shareCards.ts'

// 메신저 미리보기 카드 (2026-11-22)
// - index.html에 사이트 기본 카드 메타 태그를 넣는다.
// - 빌드 결과에 작품별 공유 페이지 share/<작품ID>/index.html을 만든다. 개발 서버에서도 같은 주소로 열 수 있다.
// - VITE_SITE_URL(배포 주소)이 있어야 이미지가 절대 주소가 된다. 없으면 빌드 경고만 내고 상대 경로로 둔다.
function sharePreview(siteUrl: string | undefined): Plugin {
  return {
    name: 'mingle-share-preview',
    transformIndexHtml: html => html.replace(/\s*<meta name="description"[^>]*>/, `\n    ${metaTags(SITE_CARD, '', siteUrl)}`),
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const match = /^\/share\/([a-z]+)\/?(?:\?.*)?$/.exec(req.url ?? '')
        if (!match || !isShareProjectId(match[1])) return next()
        if (!req.url!.split('?')[0].endsWith('/')) { res.statusCode = 301; res.setHeader('Location', req.url!.replace(/(\/share\/[a-z]+)/, '$1/')); return res.end() }
        res.setHeader('Content-Type', 'text/html; charset=utf-8')
        res.end(renderSharePage(match[1], siteUrl))
      })
    },
    buildStart() {
      if (!siteUrl) this.warn('VITE_SITE_URL이 없어 미리보기 카드 이미지가 상대 경로로 들어갑니다. 메신저 카드에 이미지가 나오지 않을 수 있어요 (frontend/README.md 참고).')
    },
    generateBundle() {
      for (const id of SHARE_PROJECT_IDS) this.emitFile({ type: 'asset', fileName: `share/${id}/index.html`, source: renderSharePage(id, siteUrl) })
    },
  }
}

export default defineConfig(({ mode }) => {
  const siteUrl = loadEnv(mode, process.cwd(), 'VITE_').VITE_SITE_URL?.trim() || undefined
  return { plugins: [react(), sharePreview(siteUrl)], server: { host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:8000' } } }
})
