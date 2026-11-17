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

## 2026-11-15 냉장고·구름섬 실제 API 연결 (브랜치 `feature/gemini-story-fridge-cloud`)

위 '현재 앱은 의도적으로 Mock만 사용' 기록은 이 작업 전 상태다. 푸르마(ConversationClient·reducer·2턴 데이터)는 변경하지 않았다.

### 구조
- 백엔드 `POST /api/sessions`(기존) → `POST /api/story-chat/conversations {project}` → `POST /api/story-chat/conversations/{id}/turns {request_id, turn, input:{text, choice_id?}}`. 조회는 `GET /api/story-chat/conversations/{id}`. 인증은 기존 X-Personal-Code.
- 프론트 API 모드는 기본 `ui_mock_v1`(냉장고 10장면·구름섬 3미션)을 사용한다. `backend/app/services/story_scenes.py`의 기본 장면과 프론트 카탈로그 간 일치는 `tests/test_story_chat.py`가 검사한다. 후속 P1에서 `story_data.py`가 저장소 루트 `data/` 또는 `STORY_DATA_DIR`의 공식 페르소나·규칙·세계관 JSON을 읽도록 추가했다. 공식 데이터가 없으면 내장 프롬프트 규칙을 사용한다.
- 두 작품의 `scenario_draft_v1`은 API에서 대화 생성 시 선택할 수 있는 별도 10턴 초안이다. 현재 프론트는 해당 세트나 입력 없는 `fixed-turns` 경로에 연결되어 있지 않다.
- 처리 `backend/app/services/story_turn_service.py`: 기존 `get_llm()`(GeminiProvider) 재사용, JSON 출력 검증(형식 오류 1회 재시도), 기존 금지어 가드레일, 연락처·이메일·긴 숫자 마스킹. 일반 `/api/chat`의 관계 점수·RAG·User Note·마케팅 Trigger는 쓰지 않는다. 스토리 페르소나 행은 비활성으로 생성돼 일반 채팅/페르소나 목록에서 제외된다(대시보드 페르소나 집계에는 표시될 수 있음).
- 중복 방지: 새 표 `story_turns`의 (conversation_id, turn_index)·(conversation_id, request_id) 고유 제약. 같은 request_id 재시도는 저장된 응답을 `replayed:true`로 반환하고 메시지를 늘리지 않는다. LLM 실패 시 아무것도 저장하지 않는다(502). 요청 turn이 서버 진행과 다르면 409(`detail.current_turn`).
- 프론트 `src/services/apiStoryClient.ts`: 세션/대화를 메모리에서 1회 생성(실패 시 다음 시도에서 재생성), choice index → `fridge-01-a` 형식 ID, 응답의 request_id·turn·completed_turns가 화면 턴과 다르면 진행하지 않는다. 구름섬은 1~3명 대사를 각 말풍선으로 표시한다. 시간 초과 90초.
- 모드: `VITE_STORY_CLIENT=api`일 때만 실제 API(기본은 기존 Mock). API 모드에서 실패하면 Mock으로 대체하지 않고 오류·재시도를 표시한다. 백엔드가 Mock 공급자로 응답하면 말풍선에 'AI 미연결 · 서버 고정 응답'을 표시하고 `data-provider/data-model` 속성을 남긴다.
- 키: 백엔드 `backend/.env`의 `GEMINI_API_KEY`(+ `LLM_PROVIDER=gemini`, 필요 시 `GEMINI_CHAT_MODEL`). GeminiProvider는 키를 URL 쿼리 대신 `x-goog-api-key` 헤더로 보내도록 바꿨다. 프론트 번들에는 키·공급자 설정이 없다.

### 실행
```bash
cd backend && LLM_PROVIDER=gemini uvicorn app.main:app --port 8000
cd frontend && VITE_STORY_CLIENT=api npm run dev
cd backend && python -m scripts.smoke_story_chat   # provider가 gemini가 아니면 실패
```

### PR #4(feature/ai-llm-local)와의 비교
- PR #4는 `backend/main.py` 별도 FastAPI 앱 + google-genai/python-dotenv 의존성 + 푸르마 전용 무상태 `/api/chat/turn`(history를 클라이언트가 전송, requestId 미사용)이다. main의 `app/` 구조·세션·대화 저장과 경로/스키마가 달라 병합·복사하지 않았다.
- 참고한 점: 사용자 입력/대화 맥락을 신뢰하지 않는 자료로 표시, JSON 출력 강제·검증, 오류 원문·키를 로그/응답에 남기지 않음. 새 의존성은 추가하지 않았다.

### 미완료·팀 확인
- 2026-11-15 초기 기본 세트에서 실제 Gemini(gemini-3.5-flash)로 냉장고·구름섬 각 첫 2장면과 구름섬 브라우저 1미션을 확인했다(당시 지연 5~12초). 상세는 `frontend/STORY_CHAT_GEMINI_REVIEW.md`. 후속 P1의 공식 프롬프트·응답 제어와 초안 10턴은 자동화 테스트 범위이며 실제 Gemini 전 구간과 적대적 입력 평가는 미실행이다.
- 냉장고 호감도·직함 승급, 장면당 최대 3회 주고받기, 구름섬 성향 점수·결과 판정은 미확정이라 구현하지 않았다(1장면 1입력 유지). 구름섬 결과는 계속 고정 나나 샘플이다.
- 가칭(가람그룹·윤 실장·한빛전자)은 확정 전이라 프롬프트에서 고유명사를 만들지 않도록 했다. 프론트 구름섬 역할 표기(비비 정비, 키키 발명가, 두두 행동파)와 바이블(비비 발명가 겸 정비, 키키 사고뭉치, 두두 버팀목)이 다르며, 프롬프트는 바이블을 따른다.
- 새로고침 후 세션 복원·개인 코드 보관, 위기 상황 공식 안내 문구, 실제 서버 통계 이벤트는 미구현. SQLite에서 LLM 호출 중 트랜잭션은 닫지만 운영 DB 검증은 하지 않았다.
