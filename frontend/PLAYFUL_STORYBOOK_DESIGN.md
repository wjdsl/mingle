# MINGLE Playful Storybook Figma 결과 및 React 적용 계획

2026-11-11. Figma 파일 v7cfdtUK2I3iHzSTpL0FNH의 04 · Playful Storybook · v1(page 17:2). 기존 페이지/프레임 보존. React 소스·스토리·원본 에셋·AGENTS 변경과 Git commit/push 없음.

## 생성한 결과물

| 프레임 | node-id | 크기 |
|---|---|---|
| Main Desktop | 18:11 | 1440×1090 |
| Main Mobile | 18:12 | 390×2080, 세로 스크롤 페이지 |
| Chat Desktop | 18:13 | 1440×900, 중앙 390px 채팅 |
| Chat Mobile | 18:14 | 390×844 |
| Story Intro / Animation States | 18:15 | 2160×1030 |
| Story Card / Component Variants | 18:16 | 1980×620 |
| Chat Bubble / Component Variants | 18:17 | 1800×550 |
| Choice Ticket / Component Variants | 18:18 | 1940×240 |
| Typography & Color System | 18:19 | 1440×1080 |

추가 테마 Chat Mobile: 푸르마 34:110, 구름섬 34:138. 도입 프로토타입 최상위 화면 30:90 → 30:97 → 30:104 → 30:113 → 18:14. 원본 배경과 메시지 내 이미지 레이어는 분리했다.

## 서체

Paperlogy/Pretendard/MaruBuri는 Figma 목록에서 확인되지 않았다. 사용자가 설치된 서체 중 선택하도록 승인하여 Noto Serif KR Bold(타이틀), Noto Sans KR(본문/버튼), Noto Serif KR Regular(지문), Space Grotesk Bold(영문 로고)를 적용했다. 최종 TEXT 노드 폰트 집합은 이 세 family로 확인했다. 요청 폰트가 설치됐다고 보고하지 않는다.

Text Styles 8개: Display 48/62, Display Mobile 31/44, Heading 23/34, Body 15/24, Label 12/18, Meta 11/17, Story 15/26, Logo 28/34. 타이틀은 책/에디토리얼 인상, 조작부는 선명한 고딕, 장면 지문은 별도 세리프로 역할을 나눴다.

## Variables 및 컴포넌트

MINGLE / Playful Storybook 컬렉션의 변수 33개: 색상 13, 간격 7, 반경/치수/타입 크기 9, 폰트 family 4. WEB 코드 문법은 --sb-* 및 --space-*에 대응한다. 의미 색상 바인딩, 컴포넌트 반경 바인딩 및 간격/패딩 바인딩 332개를 적용했다. React CSS에 실제 추가한 것은 아니다.

공통 팔레트: #FAF9F6 / #252422 / #DAD6CF / #E8E1FF / #FFF1D6. CTA와 포커스용 짙은 보라 #66528E 추가. 후보 보조색 #77736F는 밝은 바탕 대비 4.47:1, 라벤더 바탕 3.73:1이라 #625E5A로 짙게 조정했다. 주요 본문 #252422-크림은 13.89:1, 보라 CTA-흰 글자는 6.64:1이다. 전체 접근성 인증/실기기 검증 완료를 뜻하지 않는다.

컴포넌트군 4개 / 총 17개 변형:
- Story Card(21:14): Default/Hover/Focus/Pressed/Coming Soon. 종이 책등 디테일, 실제 원화, 제목/장르 위계.
- Chat Bubble(21:39): Character/User/Narration/System. 역할별 표면/타이포 구분.
- Choice Ticket(21:53): Default/Hover/Pressed/Selected/Disabled. 번호·절취선·체크 표시.
- Button(21:72): Primary/Quiet/Outline.

## 원화와 레이아웃

푸르마·냉장고는 기존 React 캡처의 실제 이미지 fill을 재사용했다. 구름섬 토토는 main 통합 worktree의 제공 WebP를 그대로 확인했고, Figma의 WebP 렌더 누락을 해결하기 위해 동일 원화를 PNG로 형식 변환하여 업로드했다. 새 캐릭터 생성·원본 이미지 변경 없음.

메인은 Desktop 3열/Mobile 세로 카드. Coming Soon은 별도 작은 배너로 분리했다. 채팅은 Desktop에도 390px 상한이며 모든 장면은 내부에 머문다. 좌우 공간은 중립 배경과 작은 에디토리얼 문구만 사용한다. 기기 목업 없음. 헤더/진행/선택지/입력은 고정, 메시지 영역만 가변 높이와 스크롤. 푸르마의 따뜻한 종이, 냉장고의 크림, 구름섬의 하늘색 표면을 동일 구조에 적용했다.

## 모션과 프로토타입 범위

냉장고 카드 클릭 → Blur 로딩 → 배경 → 지문 → 첫 메시지 → Chat 이동을 연결했다. 대기값 0.7/0.7/0.9/0.35초, Dissolve 0.2초, Skip 44px 조작 영역. 카드/티켓 Hover와 클릭 상태도 연결했다. 푸르마·구름섬 카드 클릭은 해당 대표 Chat으로 이동한다. GitHub 텍스트에는 실제 팀 저장소 hyperlink가 있다.

주의: Figma에서 연결/정적 상태를 확인한 것이며, 실제 브라우저 React에서 모션을 실행하거나 사용자 테스트한 결과는 아니다. Hover 2px 이동/Press 1px 눌림은 상태/패딩 및 사양으로 표현되며 React 구현 시 transform으로 정리한다. prefers-reduced-motion 자동 감지는 Figma 프로토타입 기능으로 구현하지 않았다. 런타임 CSS에서 이동/Blur를 생략하되 순서를 유지하도록 구현해야 한다.

## 검수와 남은 항목

Main Desktop/Mobile, Chat Desktop/Mobile, 푸르마/구름섬 테마, 도입 보드, 색상/타이포 보드, 컴포넌트 보드 렌더 확인. 이미지 누락, 지문 잘림, 마지막 카드 상태 잘림을 수정했다. 9개 주요 프레임이 편집 가능한 텍스트/Auto Layout/인스턴스로 채워졌고, 폰트 집합/변수 수/Variant 수/연결 정보를 읽어 확인했다.

미완료/후속 범위: 실제 폼/자유 입력·대화 생성은 React에 있음. Figma는 대표 흐름 프로토타입이며 모든 선택 분기/피드백 제출/관리자 인증이 동작하는 앱이 아니다. 모든 캐릭터별 감정 모션, 실제 키보드·스크린리더·360px 적용 및 실기기 QA, 이미지 로딩 실패, 실제 공유 기능, 관리자/엔딩의 Storybook 최종 비주얼은 후속이다. 기존 엔딩/관리자 레이아웃 검토 프레임은 유지했다. 실 데이터나 AI 분석을 추가하지 않았다.

## React 적용 순서

1. 확정 프레임을 get_design_context/variable defs/screenshot으로 읽고 --m-* 및 --w-*와 새 의미 토큰 매핑.
2. Home/ProjectCard/CharacterPortrait: 제목 위계/원화 구도/책등과 장르 라벨. 기존 카드 이동 유지.
3. StoryChat/ChatIntro/SceneImage: 고정 프레임·지문/버블/선택지 위계와 단계 전환 적용. 기존 useStoryChat/reducer/Mock 데이터는 유지.
4. CSS 누적 덮어쓰기 정리, 폰트 파일과 라이선스 확인 후 self-host 적용. 새 UI 라이브러리 없이 우선 구현.
5. 360/390/768/1440, 낮은 높이·키보드·모션 감소·재진입·실패/Skip 검증. Figma와 같은 뷰포트에서 비교.

자동 양방향 동기화나 Code Connect 등록은 구성하지 않았다. 디자인 확정 후 별도 승인 범위로 코드 반영한다.
