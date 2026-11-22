import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { PROJECT_CARDS, SHARE_PROJECT_IDS, SHARE_QUERY, SITE_CARD, absoluteUrl, metaTags, projectShareUrl, renderSharePage } from '../src/share/shareCards.ts'
import { projects } from '../src/projects/stories/catalog.ts'
import { SHARE_LINK_QUERY, createShareEvents } from '../src/services/shareEvents.ts'

test('공유 링크는 작품별 공유 페이지 주소이고 작품 ID와 공유 유입 표시만 담는다', () => {
  assert.equal(SHARE_QUERY, SHARE_LINK_QUERY)
  assert.equal(projectShareUrl('https://mingle.example/', 'fridge'), 'https://mingle.example/share/fridge/?from=share')
  assert.equal(projectShareUrl('https://mingle.example/app', 'cloud'), 'https://mingle.example/app/share/cloud/?from=share')
  const url = new URL(projectShareUrl('http://127.0.0.1:5173/', 'puruma'))
  assert.deepEqual([...url.searchParams.keys()], ['from'])
  assert.equal(url.hash, '')
})

test('작품 카드의 제목·소개는 catalog.ts 작품 정보와 같다', () => {
  assert.deepEqual([...SHARE_PROJECT_IDS].sort(), projects.map(p => p.id).sort())
  for (const project of projects) {
    const card = PROJECT_CARDS[project.id as keyof typeof PROJECT_CARDS]
    assert.equal(card.projectTitle, project.title)
    assert.equal(card.title, `${project.title} | MINGLE`)
    assert.equal(card.description, project.description)
  }
})

test('미리보기 이미지 파일이 public/og에 있다', () => {
  for (const card of [SITE_CARD, ...Object.values(PROJECT_CARDS)]) {
    assert.ok(existsSync(new URL(`../public/${card.image}`, import.meta.url)), card.image)
  }
})

test('배포 주소가 있으면 이미지·주소가 절대 주소, 없으면 상대 경로이고 og:url은 빠진다', () => {
  const withSite = metaTags(PROJECT_CARDS.fridge, 'share/fridge/', 'https://mingle.example')
  assert.match(withSite, /<meta property="og:image" content="https:\/\/mingle\.example\/og\/fridge\.jpg" \/>/)
  assert.match(withSite, /<meta property="og:url" content="https:\/\/mingle\.example\/share\/fridge\/" \/>/)
  assert.match(withSite, /<meta name="twitter:card" content="summary_large_image" \/>/)
  const withoutSite = metaTags(PROJECT_CARDS.fridge, 'share/fridge/', undefined)
  assert.match(withoutSite, /<meta property="og:image" content="\/og\/fridge\.jpg" \/>/)
  assert.doesNotMatch(withoutSite, /og:url/)
  assert.equal(absoluteUrl('https://mingle.example/app/', 'og/site.jpg'), 'https://mingle.example/app/og/site.jpg')
})

test('공유 페이지는 메타 태그를 갖고 작품 화면으로 넘기며, 문구는 HTML 이스케이프된다', () => {
  for (const id of SHARE_PROJECT_IDS) {
    const html = renderSharePage(id, 'https://mingle.example')
    assert.match(html, new RegExp(`<meta property="og:title" content="[^"]+ \\| MINGLE" />`))
    assert.ok(html.includes(`location.replace('../../' + location.search + '#/project/${id}')`))
    assert.ok(html.includes(`href="../../#/project/${id}"`))
  }
  assert.ok(metaTags({ ...SITE_CARD, title: 'A "B" <C> & D' }, '', undefined).includes('A &quot;B&quot; &lt;C&gt; &amp; D'))
})

test('공유 페이지에서 넘어온 주소도 기존처럼 공유 유입으로 기록된다', () => {
  const sent: unknown[] = []
  const events = createShareEvents({ enabled: () => true, newId: () => 'anon-1234', storage: () => undefined, fetcher: (async (_: unknown, init?: RequestInit) => { sent.push(JSON.parse(String(init?.body))); return new Response() }) as typeof fetch })
  // 공유 페이지 스크립트: '../../' + location.search + '#/project/<id>'
  const landed = new URL('../../' + new URL(projectShareUrl('https://mingle.example/', 'cloud')).search + '#/project/cloud', 'https://mingle.example/share/cloud/')
  assert.equal(landed.href, 'https://mingle.example/?from=share#/project/cloud')
  assert.equal(events.captureShareEntry({ search: landed.search, hash: landed.hash }), 'cloud')
  assert.deepEqual(sent, [{ anon_id: 'anon-1234', project: 'cloud', event: 'link_open' }])
})
