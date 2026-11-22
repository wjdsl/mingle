# 관리자 로그인·대시보드 (2026-11-11)

## 실행 및 계정 발급

- 관리자 주소: `http://127.0.0.1:5174/#/admin` (Vite가 다른 포트를 사용하면 해당 포트).
- 사용자 홈에는 관리자 메뉴를 노출하지 않는다. `#/admin` 이하 직접 접근도 인증 전에는 로그인 화면만 표시한다.
- Vite는 `/api`를 `http://127.0.0.1:8000`으로 프록시한다. 운영은 HTTPS 동일 출처 `/api` 리버스 프록시를 구성한다. Vite 설정은 개발 전용이다.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# .env에 본인 환경 전용 SECRET_KEY 설정 (32자 이상, 예제 기본값 사용 불가)
# 생성: .\.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python -m scripts.create_admin --id 관리자아이디   # 예: mingle-team (이메일 아니어도 됨)
# 비밀번호는 터미널에 숨김 입력 (12~200자), 회원가입 화면 없음
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 기존 계정 재발급: 동일 명령에 `--reset` 추가. 발급자는 서버/DB에 접근 가능한 팀 담당자다.
- 작품 담당자 계정(2026-11-21): `--project puruma`처럼 작품을 지정하면 `role=project` 계정이 되고 `admin_project_access` 표에 작품이 저장된다. 여러 작품은 `--project fridge --project cloud`. 작품 ID는 `puruma`/`fridge`/`cloud`만 허용한다. `--project` 없이 만들면 기존과 같은 플랫폼 관리자(`role=admin`, 전체 작품)다. `--reset`에 `--project`를 주지 않으면 계정 종류와 작품 목록을 유지한다.
- 기본 관리자 계정 자동 생성은 제거했다. 환경변수로 명시한 계정만 최초 생성하거나 CLI로 발급한다. 기존 예제 비밀번호를 쓰는 계정은 로그인/조회가 거부된다.
- 기본/빈 JWT 키로 관리자 API를 사용할 수 없다(503). 키를 변경하면 기존 개인 코드 해시 등 다른 인증에도 영향이 있으므로 기존 서버에서는 팀 담당자가 설정을 관리한다.
- 현재 실행 중인 검증 서버는 `.backups/admin-local.db`의 별도 DB와 `.backups/admin-local-access.json`의 무작위 자격 증명을 사용한다. 원본 `backend/data/app.db`를 사용하지 않는다. 편의용 로그인 정보는 `.backups/admin-local-login.txt`에만 있으며 Git에 포함되지 않는다.
- 로컬 검증 서버 재실행: 저장소 루트에서 `.backups/admin-venv/Scripts/python .backups/run-admin-local.py`. 이 파일들은 검증 환경 전용이며 팀원은 위 표준 절차를 따른다.

## 실제 연결 범위

`POST /api/admin/login` → `GET /api/admin/me`(허용 작품 `projects` 포함) → `GET /api/admin/projects/{project}/stats?days=14&data=real`.
CSV는 `GET /api/admin/projects/{project}/stats.csv?days=14&data=real`(같은 권한 검사). `data`는 `real`(기본, 샘플 제외)·`sample`(샘플만)·`all`(모두)이다.
JWT Bearer, DB 활성 상태와 역할을 서버에서 확인한다. 토큰은 React 메모리에만 보관한다. 새로고침/서비스 홈 이탈 시 다시 로그인하며, 만료/401 시 데이터를 지우고 로그인으로 돌아간다. 로그아웃은 클라이언트 토큰 폐기이며 JWT 서버 폐기 목록은 없다. 비활성 계정은 서버에서 즉시 거부한다.

### 계정과 작품 권한

- 계정 발급: `python -m scripts.create_admin --id ...`은 전체 관리자(`role=admin`, 세 작품 모두). `--project puruma`처럼 작품을 지정하면 작품 담당자(`role=project`)이며 `admin_project_access` 표에 작품이 저장된다. 여러 작품은 `--project fridge --project cloud`. `--reset`에 `--project`를 주지 않으면 계정 종류와 작품 목록을 유지한다.
- 작품 담당자는 로그인할 수 있고 배정된 작품만 작품 목록(`GET /api/admin/projects`)과 선택 상자에 보인다. 배정되지 않은 작품의 `/projects/{project}/stats`를 직접 요청하면 서버가 403을 반환한다. 화면에서 숨기는 것만으로 권한을 처리하지 않는다.
- 작품 담당자는 전체 조회 API(`/overview`, `/conversations`, `/conversations/{id}`(채팅 원문), `/triggers`)에 접근할 수 없다(403). 이 API는 전체 관리자 전용이다.
- 작품이 하나도 배정되지 않은 담당자는 빈 목록을 보고 모든 통계가 403이다.

### 채팅 모드별 기록

| 실행 모드 | 채팅 통계 | 공유 통계 | 접속·홍보·재방문 이벤트 |
|---|---|---|---|
| 브라우저 전용 Mock (`VITE_STORY_CLIENT` 기본값 / 푸르마 기본) | 서버에 기록 없음 | 요청을 보내지 않음 | 요청을 보내지 않음 |
| 서버 Mock (백엔드 `LLM_PROVIDER=mock` + `VITE_STORY_CLIENT=scenario-mock`, 푸르마 `VITE_PURUMA_CLIENT=scenario-mock`) | 기록됨 · 샘플로 구분 | 기록됨(샘플 구분 없음) | 기록됨 · 샘플로 구분 |
| 서버 연결 (`VITE_STORY_CLIENT=api`, 푸르마 `VITE_PURUMA_CLIENT=api`) | 기록됨 | 기록됨 | 기록됨 |

- **배포 주의**: 배포 빌드에 `VITE_STORY_CLIENT=api`, `VITE_PURUMA_CLIENT=api`가 없으면 브라우저 전용 Mock으로 동작해 대화와 이벤트가 서버에 아무것도 기록되지 않는다. 대시보드가 비어 있으면 먼저 빌드 환경변수를 확인한다.
- **샘플 데이터(FR-73)**: 서버 Mock의 기록은 연결한 DB에 실제로 남으므로 운영 DB에 연결하지 않는다. 남은 기록은 대시보드가 샘플로 구분한다.
  - 대화: 대화 단위로 판정한다. 저장된 턴 중 provider가 `mock`인 턴이 하나라도 있으면 샘플이다. 고정 연출(`fixed`)·AI 대체 응답(`fallback`) 턴은 Mock이 아니다. 저장된 턴이 없는 대화는 판정할 수 없어 실제 쪽에 세고 화면에 개수를 알린다.
  - 접속·홍보·재방문 이벤트: 받을 때 서버의 LLM 공급자가 `mock`이면 샘플로 저장한다.
  - 공유 이벤트: 대화와 연결되지 않아 샘플을 구분하지 않으며 모든 데이터 선택에서 같은 값을 보인다.
  - 기본 화면(실제 데이터)은 샘플을 빼고 몇 건을 뺐는지 알린다. `샘플 데이터`·`전체(샘플 포함)`를 고르면 화면과 CSV에 "샘플 데이터" 표시가 붙는다.

## 지표 및 기간 정의

오늘을 포함한 최근 7/14/30/90개의 KST 달력 일자, 첫날 00:00 KST~조회 시각. 화면 순서는 명세 A02(`data/dashboard/pruma_dashboard_metrics.json`)를 따른다. 기획서 지표 중 비율은 세션이 아니라 대화 단위로 계산한다(체험 단위가 대화이고 한 세션이 여러 번 시작할 수 있음).

### 방문 (작품별)

| 지표 | 정의 |
|---|---|
| 총 접속 수 | 기간 내 작품 시작 화면(소개)에 들어온 익명 세션(브라우저 탭) 수. 같은 탭의 재진입은 한 번 |
| 재방문율 | 기간 내 완료한 방문자 중, 그 첫 완료 뒤에 다른 세션(탭)에서 다시 시작한 방문자의 비율(0~100%). 다시 시작은 조회 시각까지의 기록을 본다. 같은 탭에서 다시 하기와 완료 전의 시작은 재방문이 아니다. 기획서 초안의 "두 번째 이상 시작한 세션 / 완료한 세션"은 분자가 분모에 포함되지 않아 100%를 넘을 수 있어 2026-11-22에 바꿨다 |
| 시작한 방문자 | 기간 내 체험을 시작한 방문자(브라우저 익명 ID) 수 |

- 방문자 ID는 localStorage `mingle.visitor.v1`의 무작위 값이다. 서버에 연결한 모드에서 체험을 시작할 때 처음 만들고, 체험 시작·완료 이벤트에만 보낸다. 호칭·대화·진행 저장·기기 정보와 연결하지 않는다. 브라우저 사이트 데이터를 지우면 초기화되며, 저장소를 쓸 수 없는 환경(비공개 모드 등)에서는 탭 메모리에만 있어 재방문으로 잡히지 않는다.

### 채팅 (작품별)

| 지표 | 정의 |
|---|---|
| 채팅 이용 세션 | 기간 내 해당 작품의 대화를 시작한 세션 수(중복 제거) |
| 시작한 대화 | 기간 내 생성된 해당 작품의 대화. 냉장고·구름섬은 이전 장면 세트(`ui_mock_v1`)와 현재 시나리오 세트(`scenario_draft_v1`)의 대화를 같은 작품으로 합산 |
| 완료율 | 위 대화 중 서버에서 완료(`completed`) 처리된 비율(현재 상태 기준). 대화가 없으면 `—` |
| 진행 턴 | 위 대화에서 서버에 저장된 턴 합계와 대화당 평균. 장면형 대화(세 작품의 `/api/story-chat`)는 저장된 장면 턴(`story_turns`), 이전 푸르마 대화(`/api/chat`)는 서버 진행 상태(`turn_count`). 같은 요청 ID의 재시도, 실패, 위기 안내로 저장되지 않은 입력은 세지 않음 |
| 체류 시간(근사) | 대화의 저장된 첫 턴 시각부터 마지막 턴 시각까지. 턴 시각이 2개 이상인 대화의 중앙값과 p90. 첫 장면을 읽는 시간과 마지막 턴 뒤의 시간은 들어가지 않는다 |
| 구간 도달률 | 현재 장면 세트(냉장고·구름섬 `scenario_draft_v1`, 푸르마 `puruma_draft_v1`)로 시작한 대화 중 구간 첫 장면을 받은 대화의 비율(저장된 턴 수 ≥ 구간 시작 턴 번호 - 1). 구간은 푸르마 6구간(`puruma_scenes.SECTIONS`), 냉장고·구름섬은 장면 카드 초안 JSON의 `phases`. 이전 장면 세트 대화는 구간 정의가 달라 분모에서 빼고 개수를 알린다 |
| 엔딩 분포 | 현재 장면 세트의 끝난 대화를 저장된 턴 기록으로 다시 판정한 결말별 도달 수와 비율. 판정 규칙은 대화 중 결말 판정과 같다(`story_judgement`, `puruma_state`). 결말은 따로 저장하지 않으므로 점수표가 바뀌면 지난 대화의 분포도 바뀐다 |
| 관심 분야 | 푸르마 자유 입력 턴에 저장된 주제(6종)의 분포. 분류가 저장되지 않은 턴(AI 대체 응답·샘플)은 분모에만 들어간다. 냉장고·구름섬은 해당 없음 |
| AI 대체 응답 비율(운영용) | 장면 턴 중 고정 연출을 뺀 턴에서 AI 실패로 장면 고정 대사가 나간(`fallback`) 비율과 사유 코드별 건수. 기획서 지표가 아니다 |
| 일별 | 대화 시작일 기준 대화 수·진행 턴 |

### 공유 (작품별, 결과 화면)

| 지표 | 정의 |
|---|---|
| 링크 공유 버튼 | 결과 화면의 `작품 링크 공유` 버튼을 누른 횟수. 누른 시점에 한 번만 센다(네이티브 공유 → 링크 복사로 넘어가도 추가로 세지 않음). 외부에 실제로 올렸는지는 알 수 없다 |
| 이미지 저장 버튼 | 결과 화면의 `이미지 저장` 버튼을 누른 횟수(저장 성공 여부와 무관) |
| 공유 링크 열기 | 공유 링크(`?from=share#/project/<작품>`)로 열린 세션 수. 일반 작품 링크 방문은 세지 않으며, 같은 세션의 재열기는 한 번 |
| 링크로 체험 시작 | 공유 링크로 들어온 세션이 호칭 입력 화면의 시작 버튼을 눌러 체험을 시작한 세션 수 |

- 이벤트는 `POST /api/events/share`(로그인 없음)로 `anon_id`(브라우저 탭 단위 무작위 값), `project`, `event`만 받는다. 서버는 여기에 시각을 붙여 `share_events` 표에 저장한다. 그 밖의 필드는 422로 거부한다. 호칭·대화·결과 내용·개인 코드는 보내거나 저장하지 않으며 공유 링크에도 넣지 않는다.
- 같은 `anon_id`가 한 시간에 60건을 넘으면 이후 요청은 저장하지 않는다(남용 방지).
- `이미지 저장`은 결과 카드를 브라우저에서 PNG로 그려 사용자 기기에 내려받는다. 서버로 업로드하지 않는다.

### 홍보 (작품별)

| 지표 | 정의 |
|---|---|
| 노출 | 홍보 카드가 화면에 절반 이상 보인 세션 수. 세션·콘텐츠당 한 번 |
| 클릭 | 홍보 카드를 누른 횟수(같은 세션의 반복 포함)와 누른 세션 수 |
| 클릭률 | 클릭한 세션 ÷ 노출된 세션(콘텐츠별·전체) |

- 콘텐츠는 서버 허용 목록(`services/analytics_events.py`)에 있는 것만 받는다. 푸르마는 구간에 배정된 RAG 항목 중 `data/rag/pruma_rag_mvp.json`에 확인된 URL이 있는 7개다.
- 냉장고·구름섬의 결과 화면 영화관 바로가기는 URL이 정해지지 않아 화면에 "해당 없음"으로 표시한다. URL이 정해지면 허용 목록의 `PENDING_PROMOS`에 콘텐츠 ID를 넣고 결과 화면에서 노출·클릭을 보내면 된다.
- 클릭 기록은 링크 이동을 막지 않는다. 기록 요청이 실패해도 링크는 열린다.

### 통계 이벤트 수집

- `POST /api/events/track`(로그인 없음). 기획서 7장 필드 `session_id`(탭 단위 무작위 값, 공유 이벤트의 `anon_id`와 같은 값), `project`, `event_type`, `section`, `turn`, `content_id`와 재방문용 `visitor_id`를 받는다. 시각은 서버가 붙여 `analytics_events` 표에 저장한다.
- 이벤트 종류: `entry_view`(시작 화면 진입), `story_start`·`story_complete`(체험 시작·완료, `visitor_id`는 이 둘에만), `promo_impression`·`promo_click`(`content_id` 필수).
- 허용 목록 밖의 종류·콘텐츠 ID, 그 밖의 필드(호칭·원문·timestamp 등)는 422로 거부한다. 같은 세션이 한 시간에 60건을 넘으면 저장하지 않는다. 시작 화면 진입과 홍보 노출은 세션(·콘텐츠)당 한 번만 저장한다.
- 공유 이벤트(`share_events`)와는 별도 표다. 기존 공유 통계 집계는 바뀌지 않는다.

### CSV 내려받기 (FR-74)

- 화면의 `CSV 내려받기`는 선택한 작품·기간·데이터의 집계 수치만 담는다(구분·지표·항목·값). 개별 이벤트, 세션·방문자·대화 ID, 원문은 넣지 않는다. 엑셀에서 한글이 깨지지 않도록 UTF-8 BOM을 붙인다.
- 작품 담당자는 배정된 작품만 내려받을 수 있다(다른 작품은 403).

그래프에는 키보드로 선택 가능한 수치와 일별 표를 제공한다. 조회 중 이전 기간의 수치를 제거하고, 실패/재시도/빈 상태를 구분한다. 요청 취소·15초 타임아웃으로 이탈 및 무응답을 처리한다.

## 후속 연동

- 영화관 바로가기 URL이 정해지면 홍보 지표를 냉장고·구름섬에도 연결한다(위 홍보 절).
- 기존 전체 조회 API(`/overview` 등)는 전체 관리자용으로 남아 있으며 화면은 작품별 통계 API를 사용한다.
- 감정 분석·워드클라우드·콘텐츠 편집은 이번 범위에서 미구현이다. 새 통계를 위해 채팅 원문을 추가 수집하지 않았다.
- 공개 배포 전 로그인 요청 제한, 서버 로그아웃/토큰 폐기, 운영 계정 발급·비밀키 관리 및 HTTPS 배포 정책 검토. 현재 조회 대시보드는 콘텐츠 변경 API를 추가하지 않는다.

## 파일과 검증

프론트: `features/admin/{AdminApp.tsx,metrics.ts}`, `services/adminClient.ts`, `services/analyticsEvents.ts`, `services/shareEvents.ts`, `services/resultImage.ts`, `services/shareProject.ts`, `features/platform/{Platform,shared,StoryResult}.tsx`, `features/chat/ChatScene.tsx`(홍보 카드), `tests/{admin,shareEvents,analyticsEvents}.test.ts`.
서버: `api/routes/{admin,events}.py`, `api/deps.py`(`get_dashboard_admin`), `services/{admin_access,project_stats,analytics_events,stats_csv}.py`, `db/models.py`(`AdminProjectAccess`, `ShareEvent`, `AnalyticsEvent`), `scripts/create_admin.py`, `tests/{test_project_stats,test_project_stats_metrics,test_analytics_events,test_admin_project_access}.py`.

검증 결과는 작업 완료 보고를 따른다. DB·pycache·Images·.backups·실제 .env는 커밋 대상이 아니다.


### 대시보드 1·2차 검증 결과 (2026-11-22)

- 백엔드 `pytest -q` 415개, 프론트 테스트 101개·`npm run build`, 데이터 검증 4종(대시보드 19, 개요 52, 구름섬 79, 냉장고 112) 통과. 추가 테스트: 샘플/실제 구분, 구간 도달률, 엔딩 분포(대화 API 결말과 대조), 체류 시간, AI 대체 응답 비율, 이벤트 입력 검사·남용 제한, 접속 중복 제거, 홍보 노출·클릭·클릭률, 재방문율(100% 이하), CSV 내용과 작품 담당자 403, 공유 통계 회귀.
- 서버 Mock과 임시 DB로 브라우저 확인: 세 작품 시작 화면 진입, 푸르마 10턴과 홍보 카드 4종 노출·클릭, 냉장고 10턴과 결과·공유, 구름섬 중도 이탈, 새 탭 이어하기로 재방문 1건, 관리자 화면 수치(기대값 일치), CSV 내용(curl), 작품 담당자 권한, 375px 레이아웃, 브라우저 전용 Mock에서 이벤트 미전송.
- 미검증: CSV 버튼의 실제 파일 저장(단위 테스트로만 확인), PostgreSQL, 실제 Gemini/Qwen 연결 상태의 지표, 실기기.

### 이전 검증 결과 (2026-11-22, 대시보드 이전)

- 백엔드 `pytest -q` 309개 통과(작품별 집계, 이전/현재 장면 세트 합산, 재시도·위기 안내 제외(푸르마 포함), 기간 필터, 작품 담당자 403, 공유 이벤트 분리·입력 제한). 프론트 테스트 58개·`npm run build` 통과.
- 이전 작업에서 서버 Mock 임시 DB로 공유 링크 진입 → 10장면 완료 → 공유·이미지 저장 → 담당 계정 대시보드 반영을 브라우저로 확인했다. 이번 검토에서는 8000 포트의 기존 서버(공유 API 이전 코드)를 종료하지 못해 브라우저 확인을 다시 하지 않았다.
- 미검증: 실제 Gemini/Qwen 연결 상태, 푸르마 서버 연결 화면의 대시보드 반영(백엔드 테스트로만 검증), 네이티브 공유 시트, 모바일 실기기 이미지 저장, 운영 DB.
