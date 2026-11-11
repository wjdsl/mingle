# 프론트엔드와 백엔드·AI 연동 인계

2026-11-11. Figma 기반 Playful Storybook을 **React에 적용한 버전**이다. 대화는 계속 Mock이며 실제 API/LLM·저장·성향 분석·서버 인증·관리자 화면을 연결한 버전이 아니다.

## 실행과 확인

Node 22.15.1 기준. frontend에서 npm ci → npm run dev. npm run build, npm test로 검증한다. 로컬 확인 주소는 http://127.0.0.1:5174/ (실행 포트는 Vite 출력 확인). hash 경로는 #/project/puruma, #/project/fridge, #/project/cloud. API 키는 프론트 환경변수에도 넣지 않는다.

## 현재 소유 경계

- Platform: 홈/작품/호칭/채팅/결과 및 History API, 세션 key. 현재 새로고침하면 메모리 상태 초기화.
- StoryChat + useStoryChat: 냉장고10턴/구름섬3미션, 입력/선택/대기/실패/재시도/다음장면.
- services/storyClient.ts: StoryClient.sendTurn(request, signal) 주입 경계. requestId, project, turn(0부터), input.text/input.choice를 넘기며 응답은 speaker/text/reaction이다. mockStoryClient가 기본값이다.
- 실제 클라이언트는 **ChatLayout의 client prop** 또는 useStoryChat 네 번째 인자로 주입한다. 현재 앱은 의도적으로 Mock만 사용한다. 이름만 API 모드인 스위치는 없다.
- 푸르마는 기존 ConversationClient를 유지한다. features/chat/useChat(client)의 sendTurn(request,signal), types.ts의 TurnRequest/TurnResponse에 맞춰 adapter를 제공한다. mockConversationClient가 기본값이다. 새 UI에서도 reducer와 2턴 샘플 데이터는 그대로다.

## 기존 main API와의 차이

작업 시작 시 fetch한 origin/main@d3d2306 및 backend/app/schemas/chat.py, api/routes/chat.py를 확인했다.

- 기존 일반 응답: POST /api/chat (api_prefix=/api), body {conversation_id, message}.
- 사용자 세션은 get_current_session에서 X-Personal-Code 등으로 검증하고 conversation 소유권도 확인한다. 일반 사용자 무로그인 UX와 개인 코드 세션 설계의 연결은 팀 합의가 필요하다.
- 응답에는 reply 외 state, story_events, ending, notes_updated, sources, triggers, guardrail_triggered 등이 있다. 세션/대화 생성·복원 후 conversation_id를 보관하는 adapter/lifecycle이 선행되어야 한다.
- 현재 UI의 StoryClient는 Mock 대사 교체 경계다. 백엔드 response를 reply만으로 잘라 연결하면 서버 진행/엔딩/안전 이벤트를 잃는다. 실제 연결 시 서버 state/ending/events를 UI 모델에 매핑하고, useStoryChat.advance의 로컬 턴 전환을 서버 권위 진행으로 바꾸어야 한다.
- 현재 requestId는 재시도 중 같은 UI 요청을 유지하기 위한 값이며 기존 HTTP ChatRequest에 해당 필드가 없다. 서버의 idempotency를 구현한 것으로 간주하지 말 것. 재시도 중복 생성 방지는 서버와 별도 계약 필요.
- input.choice(인덱스)와 UI project 객체를 백엔드에 그대로 보내지 않는다. 서버 persona/scene/choice 식별자 계약에 매핑한다. 프로젝트별 시나리오 길이/엔딩 규칙은 서버가 확정해야 한다.
- AI 실험 브랜치의 다른 경로/스키마를 main 계약과 혼합하지 않는다. 이번 PR/커밋은 백엔드/data/prompts를 수정하지 않는다.

## 실제 연결 작업 순서

1. 세션 생성·복원/대화 시작 API와 프로젝트 persona 매핑 합의.
2. HTTP adapter에 인증/요청 취소/오류 분류를 구현. API key는 서버만 보유.
3. 응답 state/ending/events 및 guardrail에 따라 UI 갱신. Mock choice/reply/result 사용 중단 조건 명시.
4. 타임아웃·401/403/409/429/5xx·취소·재시도와 서버 중복 방지 확인.
5. 샘플 안내를 실제 연결 확인 후에만 변경. 단순 어댑터 파일 생성만으로 AI 연동 완료라고 보고하지 않는다.

## 기타 미연동 기능

- 피드백: services/feedback.ts의 입력·복사만 제공, 실제 저장 API 없음. 성공 안내는 ‘복사’라고 명시.
- 공유: shareProject.ts는 작품 소개 URL을 네이티브 공유/클립보드/수동 복사한다. 결과 이미지 공유나 결과 저장이 아니다.
- 관리자: main에는 JWT 관리자 API와 최근 대시보드 데이터 검증 작업이 있지만, 현재 React에 관리자 라우트/로그인/대시보드 UI는 없다. 이번 범위에서 보류. 프로젝트별 서버 인가와 통계 schema는 별도 통합할 것.
- 구름섬 결과는 고정 나나 샘플이며 실제 분석이 아니다. 냉장고 엔딩도 고정 Mock 예고편이다.

## 디자인 연결

Figma: https://www.figma.com/design/v7cfdtUK2I3iHzSTpL0FNH
Main 18:11/18:12, Chat 18:14, Desktop 18:13. 상세 설계는 PLAYFUL_STORYBOOK_DESIGN.md.
styles/storybook.css가 --sb-* 의미 토큰과 기존 --m-*·--w-*의 대응 계층이다. 기존 플랫폼/푸르마 CSS와 기능을 보존해 후순위 적용한다. Noto Serif KR/Noto Sans KR/Space Grotesk은 Google Fonts 공식 WOFF2를 자체 호스팅하며 라이선스는 src/assets/fonts/*-OFL.txt. CSS의 unicode-range로 필요한 subset만 요청된다. 새 npm 의존성 없음.

Figma 대표 화면과 달리 실제 스토리의 대사/지문/반응·진행 보기·이미지 설명·에러/로딩 상태는 보존했다. 결과 화면은 행동 영역이 첫 화면 아래로 밀리던 문제를 줄였으며 폰트/색/반경을 공통 적용했다. 전체 원화·기획/데이터는 임의 변경하지 않았다.

## 검증 결과

- TypeScript/Vite 빌드, 단위 테스트10개 통과.
- 브라우저: 냉장고10턴, 구름섬3미션, 푸르마2턴과 각 결과 이동 확인.
- 자유 입력 → Mock 실패 → 재시도에서 사용자 메시지 1→1, 뒤로/앞으로에서 진행 보존.
- 360/390/768/1440 가로 넘침 없음, 홈1/1/2/3열. Desktop에서도 채팅390 상한 유지.
- 390×460에서 로그198px, 입력 하단452px로 화면460px 내부에 유지.
- 이미지 확대/닫기, ··· 의견 dialog 진입, Skip 확인. 콘솔 error 없음(검증 탭 로그).
- 실제 서버/LLM 호출, 로그인/관리자, 실제 OS 공유 전송, 실제 휴대폰 키보드/스크린리더, 이미지 네트워크 실패 시뮬레이션은 미검증.
