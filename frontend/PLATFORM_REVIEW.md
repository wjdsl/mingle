# MINGLE 플랫폼 구현 및 검증 기록

작성일: 2026-11-08. 범위: 현재 `feature/frontend-ui` 작업 트리의 3개 작품 프론트 Mock 프로토타입.

## 사전 분석과 팀 원격 참고

- React 19, Vite 8, TypeScript, 일반 CSS. 라우터/상태관리/UI 패키지는 없었다. 기존 코드는 `main.tsx`에서 `ChatScene`을 직접 렌더링했다.
- 실제 기존 범위는 푸르마 시작 → 에피소드 → 개강 2턴 Mock, 자유 입력·선택지·리액션·내부 스크롤, 유저노트 빈 상태, 졸업 앨범/엔딩 카드 디자인 샘플이었다. 통합 홈/Coming Soon 카드의 실행 코드는 없었다.
- 작업 시작 시 추적 파일의 수정은 없었고 `Images/`만 미추적 상태였다. 원본 이미지 폴더는 수정하지 않았다.
- `AGENTS.md`, `FRONTEND_DESIGN.md`, 루트/프론트 README와 기존 소스·스타일·Mock을 읽었다. PM 문서는 처음에는 로컬 `docs/planning`에서, 사용자 후속 요청 뒤에는 fetch한 최신 `origin/main`에서 확인했다.
- 검토 원격: `https://github.com/wjdsl/mingle.git`. `origin/main@c2ebc2e`(대시보드 데이터 설계 v0.4), `origin/feature/backend@a70b2da`, `origin/feature/ai-llm-local@935a912`를 확인했다. main의 프론트 코드는 기존 로컬 기반과 같았다.
- 최신 SRS/푸르마 기획, 데이터 설계 v0.4, AI 설계와 백엔드/실험 Chat API를 참고했다. main 백엔드는 conversation 기반, Gemini 실험은 `/api/chat/turn`으로 계약이 달라 임의 통합하지 않았다. 팀 기획·서버·데이터 파일은 수정하지 않았다.
- 원격은 프론트 설계서를 `docs/FRONTEND_DESIGN.md`로 옮겼다. 현재 브랜치는 루트 파일이므로 해당 파일에 구현 부록을 덧붙였다. 향후 통합할 때 원격 경로에 반영할 필요가 있다. 브랜치 병합/커밋/푸시는 하지 않았다.
- ‘밍글 스토리 후보.pdf’는 접근 가능한 작업 트리에 없었다. PDF 5·8페이지를 확인한 것으로 간주하지 않고 사용자 제공 두 작품 설정을 사용했다.

## 화면별 구현

| 화면 | 동작/표현 |
|---|---|
| MINGLE 홈 | 무채색 에디토리얼 Hero, 포스터 중심 세 작품 카드, 작품 둘러보기 앵커, 별도 Coming Next, Mock 안내. 모바일 세로 목록/태블릿·데스크톱 3열 |
| 공통 작품 소개 | 개별 테마, 소개·장르·체험 방식, 시작 CTA, 홈 복귀 |
| 공통 준비 화면 | 푸르마 단일 캐릭터 확인, 회장 소개, 구조대 5명 이름/역할, 별명 입력(최대 12자), 빈 값 기본 호칭 |
| 푸르마 | 기존 시작/개강 소개/2턴 채팅, 감정 이미지와 반응, 호칭 표시, 유저노트 빈 상태·앨범 유지. 종료 후 기존 졸업 카드 샘플 연결 |
| 냉장고 회장님 | 수상한 중고 거래 → 첫 이사회 → 한 끼. 선택별 코믹 대사·스티커, 표정/온도 디스플레이·황금 명패, 고정 Mock 엔딩 |
| 구름섬 | 바람섬 → 구름다리 → 균형 복구. 토토·비비·나나·키키·두두의 협동 중심 시나리오, 화자 구분, 사건 카드·단계 진행 UI, 나나 고정 샘플 결과 |
| 신규 공통 채팅 | 3단계, 선택지와 직접 입력, 300 Unicode 문자 제한·IME 보호·중복 전송 방지, 비동기 로딩, Mock 실패/재시도, 메시지/단계 진행·자동 스크롤 |
| 결과 | 샘플 표시, 작품 소개 링크 공유(네이티브/클립보드/수동 복사), 재도전·홈 복귀. 호칭/대화/결과는 공유 링크에 포함하지 않음 |

작품 직접 진입은 `#/project/puruma`, `#/project/fridge`, `#/project/cloud`다. 해시는 작품 이동만 표현하며 내부 단계는 React 메모리 상태다. 새로고침하면 초기화한다.

## 컴포넌트와 디자인 시스템

기존 재사용: `ChatScene`, `useChat`, `chatReducer`, `useViewportHeight`, `EndingCollection`, `EndingCard`, 푸르마 이미지·기존 CSS. 기존 reducer와 Mock 응답의 내용/판정은 바꾸지 않았다.

신규 공통: `AppShell`, `ProjectCard`, `ProjectIntro`, `ChatLayout`, `ChatBubble`, `MessageComposer`, `ChoiceButton`, `CharacterPortrait`, `ProgressIndicator`, `ReactionEffect`, `ResultCard`, `LoadingState`, `ErrorState`. 작품 설정을 받아 사용하며 푸르마의 전용 세부 UI를 억지로 이 구조에 끼우지 않았다.

브랜드 `--m-*`와 작품 `.theme-*`의 `--w-*`를 `platform.css`에 중앙 관리한다. 새로운 작품은 catalog와 테마를 추가하면 공통 흐름을 사용할 수 있다. 별도 원화는 `CharacterPortrait`에 연결한다. 다른 진행 규칙이나 실제 분석은 별도 구현이 필요하다.

모바일 safe-area, Visual Viewport, 포커스 표시, 장면/다음 버튼 포커스 이동, 최소 44px 주요 입력·버튼, reduced-motion을 적용했다. 푸르마 공유 버튼은 앨범 복귀 버튼과 한 줄에 배치하고 작은 높이의 카드 영역은 내부 스크롤로 원화를 보존한다.

텍스트 대비 계산: 브랜드 본문 14.85:1, 회장 주요 버튼 6.01:1. 구름섬 Primary 배경/Ink 조합은 4.05:1이라 주요 버튼을 Deep Blue/White(4.68:1)로 보완했다. 연보라 스티커의 작은 글자는 본문색을 사용한다. 이는 지정한 주요 조합의 계산이며 모든 픽셀/상태에 대한 전수 접근성 인증은 아니다.

## 수정/추가 파일 전체

| 파일 | 변경 |
|---|---|
| `AGENTS.md` | 현재 구현·테마·팀 원격 검토 기록 추가. 기존 팀 규칙/기획 보존 |
| `FRONTEND_DESIGN.md` | 플랫폼 구현 부록, Mock/연동 경계·원격 문서 경로 기록 |
| `frontend/README.md` | 3작품 경로·흐름·오류 시연·테스트·한계 안내 |
| `frontend/PLATFORM_REVIEW.md` | 이 분석/구현/검증 보고서 |
| `frontend/index.html` | 플랫폼 메타데이터, viewport-fit |
| `frontend/package.json` | 기존 test 명령에 신규 테스트 파일 추가. 의존성 변경 없음 |
| `frontend/src/main.tsx` | Platform 진입점·스타일 연결 |
| `frontend/src/features/platform/Platform.tsx` | 홈·공통 화면/컴포넌트·해시 진입·신규 대화 상태 |
| `frontend/src/features/platform/platform.css` | 브랜드/작품 토큰, 반응형·모션·접근성·CSS 콘셉트 아트 |
| `frontend/src/projects/stories/catalog.ts` | 세 작품 소개/캐릭터, 신규 시연 시나리오·고정 결과 |
| `frontend/src/services/mockStoryClient.ts` | 취소 가능한 신규 Mock 응답·선택 응답·화자 처리·실패 시연 |
| `frontend/src/services/shareProject.ts` | 개인정보를 포함하지 않는 작품 링크 공유와 복사 폴백 |
| `frontend/src/features/chat/ChatScene.tsx` | 표시용 호칭 prop, 기존 엔딩 샘플로 가는 완료 CTA |
| `frontend/src/features/endings/EndingCollection.tsx` | 직접 샘플 진입 prop, 작품 링크 공유 |
| `frontend/src/features/endings/endings.css` | 샘플 하단 버튼 배치·복사 입력·작은 카드 영역 스크롤 |
| `frontend/tests/stories.test.ts` | 신규 비동기 Mock 검증 3건 |

## 실행한 검증

- `frontend/`에서 `npm run build`: TypeScript와 Vite 프로덕션 빌드 통과.
- `frontend/`에서 `npm test`: 총 8건 통과. 기존 입력 경계·중복/오래된 응답·재시도·2턴 종료/초기화·감정 보존 5건 + 신규 선택/자유 입력과 화자 구분·취소·실패 후 재시도 3건.
- `git diff --check`: 오류 없음. Windows LF→CRLF 정규화 안내는 발생했다.
- 내장 브라우저에서 실제 화면 클릭/입력: 세 작품 소개와 호칭, 푸르마 두 턴과 졸업 카드 샘플, 냉장고 3단계(선택/자유 입력)와 결과·재도전, 구름섬 5명 소개·다중 화자·진행·결과를 확인했다.
- 구름섬 `?mockError=once`에서 최초 실패 시 진행 0, 재시도 후 진행 1을 확인했다. 사용자 메시지는 1개로 유지됐다. 자유 입력 실패/복구 후 결과 카드까지 도달했다.
- 360×844, 390×844, 768×1024, 1440×900에서 홈/공통 대화 영역의 가로 넘침이 없음을 DOM 크기로 확인했다. 모바일 한 열·큰 화면 그리드/사이드 패널도 확인했다. 세 작품의 모든 내부 상태를 네 해상도에 대해 전수 검사한 것은 아니다.
- 공통 채팅에서 composer 하단은 모바일 844px, 데스크톱 900px 뷰포트 안에 위치했다. 390×460 축소 높이에서도 composer 하단 460px, 대화 영역 약 122px로 입력/대화 영역을 유지했다. 이는 키보드 높이를 가정한 뷰포트 검사이지 실제 iOS 키보드 테스트는 아니다.
- 포커스가 응답 후 다음 버튼, 다음 장면 후 상황 카드, 결과 후 화면 컨테이너로 이동하는 것을 접근성 트리에서 확인했다. 라벨/로그/진행 상태도 트리에서 확인했다.
- 코드 검토로 IME Enter 조건, reduced-motion, 요청 취소, 공유 URL에서 검색 파라미터·대화·호칭 제외를 확인했다.

검증 과정에서 최초 npm 재검증을 루트에서 실행해 package.json 부재로 실패한 뒤, 올바른 `frontend/`에서 다시 실행해 성공했다. 최초 sandbox 로컬 미리보기 접근이 차단되어 로컬 전용 서버를 권한 검토 후 실행하고 브라우저 검증을 완료했다. 이 환경 문제를 앱 성공/실패로 집계하지 않았다.

## 미구현·미확정·추가 에셋

- 실제 LLM/백엔드 연결, 전체 스토리, AI 발화 분석/성향 매칭/엔딩 판정, 도감 획득·영구 저장/복원, 이미지 다운로드, 관리자·통계는 이번 구현 범위가 아니다. 신규 결과는 입력과 무관한 고정 샘플이다.
- 시나리오/새 대사는 사용자 설정을 바탕으로 쓴 PM 검토 전 초안이다. 푸르마 전체 학기/실제 엔딩 기획을 대체하지 않는다.
- 신규 캐릭터·표정·포스터 원화가 없어 CSS 콘셉트 아트/심벌을 사용했다. 구름섬 다섯 대원의 정식 외형은 정하지 않았다. 별도 권리 확인된 포스터, 각 캐릭터와 회장 표정 원화가 필요하다.
- 지정 폰트명은 토큰에 있으나 배포 가능한 파일은 제공되지 않았다. 시스템 폴백으로 동작하며 외부 CDN·폰트 의존성을 추가하지 않았다. Pretendard/Space Grotesk/Black Han Sans/Jua 파일과 라이선스가 후속 에셋이다.
- 실제 공유 시트에서 수신자에게 전송, OS 클립보드 권한 실패의 실제 재현, 실기기 iOS/Android 키보드·safe-area, 스크린리더, 실제 한글 IME, OS reduced-motion은 별도 검증이 필요하다. 외부에 메시지를 보내는 공유 시험은 수행하지 않았다.
- 실제 API/학교 홍보 링크/백엔드·인증 테스트는 수행하지 않았다. 팀 최신 코드의 구현 품질/운영 준비 상태를 이번 프론트 검사로 보증하지 않는다.
- 별도 lint 스크립트는 없다. 패키지/잠금 파일 의존성 변경, Commit/Push/Merge, 배포는 수행하지 않았다.
