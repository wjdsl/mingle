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
- **작품 담당자는 아직 로그인할 수 없다.** 작품별 통계 필터와 권한 검사가 없어 로그인과 모든 관리자 API에서 403("작품 담당자용 대시보드는 아직 준비 중")을 반환한다. 필터 구현 후 허용한다.
- 기본 관리자 계정 자동 생성은 제거했다. 환경변수로 명시한 계정만 최초 생성하거나 CLI로 발급한다. 기존 예제 비밀번호를 쓰는 계정은 로그인/조회가 거부된다.
- 기본/빈 JWT 키로 관리자 API를 사용할 수 없다(503). 키를 변경하면 기존 개인 코드 해시 등 다른 인증에도 영향이 있으므로 기존 서버에서는 팀 담당자가 설정을 관리한다.
- 현재 실행 중인 검증 서버는 `.backups/admin-local.db`의 별도 DB와 `.backups/admin-local-access.json`의 무작위 자격 증명을 사용한다. 원본 `backend/data/app.db`를 사용하지 않는다. 편의용 로그인 정보는 `.backups/admin-local-login.txt`에만 있으며 Git에 포함되지 않는다.
- 로컬 검증 서버 재실행: 저장소 루트에서 `.backups/admin-venv/Scripts/python .backups/run-admin-local.py`. 이 파일들은 검증 환경 전용이며 팀원은 위 표준 절차를 따른다.

## 실제 연결 범위

`POST /api/admin/login` → `GET /api/admin/me`(허용 작품 `projects` 포함) → `GET /api/admin/projects/{project}/stats?days=14`.
JWT Bearer, DB 활성 상태와 역할을 서버에서 확인한다. 토큰은 React 메모리에만 보관한다. 새로고침/서비스 홈 이탈 시 다시 로그인하며, 만료/401 시 데이터를 지우고 로그인으로 돌아간다. 로그아웃은 클라이언트 토큰 폐기이며 JWT 서버 폐기 목록은 없다. 비활성 계정은 서버에서 즉시 거부한다.

### 계정과 작품 권한

- 계정 발급: `python -m scripts.create_admin --email ...`은 전체 관리자(`role=admin`, 세 작품 모두). `--project puruma`처럼 작품을 지정하면 작품 담당자(`role=project`)이며 `admin_project_access` 표에 작품이 저장된다. 여러 작품은 `--project fridge --project cloud`. `--reset`에 `--project`를 주지 않으면 계정 종류와 작품 목록을 유지한다.
- 작품 담당자는 로그인할 수 있고 배정된 작품만 작품 목록(`GET /api/admin/projects`)과 선택 상자에 보인다. 배정되지 않은 작품의 `/projects/{project}/stats`를 직접 요청하면 서버가 403을 반환한다. 화면에서 숨기는 것만으로 권한을 처리하지 않는다.
- 작품 담당자는 전체 조회 API(`/overview`, `/conversations`, `/conversations/{id}`(채팅 원문), `/triggers`)에 접근할 수 없다(403). 이 API는 전체 관리자 전용이다.
- 작품이 하나도 배정되지 않은 담당자는 빈 목록을 보고 모든 통계가 403이다.

### 채팅 모드별 기록

| 실행 모드 | 채팅 통계 | 공유 통계 |
|---|---|---|
| 브라우저 전용 Mock (`VITE_STORY_CLIENT` 기본값 / 푸르마 기본) | 서버에 기록 없음 | 요청을 보내지 않음 |
| 서버 Mock (백엔드 `LLM_PROVIDER=mock` + `VITE_STORY_CLIENT=scenario-mock`) | 서버 DB에 기록되어 집계에 포함 | 기록됨 |
| 서버 연결 (`VITE_STORY_CLIENT=api`, 푸르마 `VITE_PURUMA_CLIENT=api`) | 기록됨 | 기록됨 |

서버 Mock의 기록은 연결한 DB에 실제로 남으므로 운영 DB에 연결하지 않도록 주의한다. 대시보드는 DB의 값을 그대로 집계하며 Mock 여부를 구분해 표시하지 않는다.

## 지표 및 기간 정의

오늘을 포함한 최근 7/14/30/90개의 KST 달력 일자, 첫날 00:00 KST~조회 시각. 이번 범위의 지표는 아래 두 묶음이며 총 접속 수, 재방문율, 엔딩 분포 등은 포함하지 않는다.

### 채팅 (작품별)

| 지표 | 정의 |
|---|---|
| 채팅 이용 세션 | 기간 내 해당 작품의 대화를 시작한 세션 수(중복 제거) |
| 시작한 대화 | 기간 내 생성된 해당 작품의 대화. 냉장고·구름섬은 이전 장면 세트(`ui_mock_v1`)와 현재 시나리오 세트(`scenario_draft_v1`)의 대화를 같은 작품으로 합산 |
| 완료율 | 위 대화 중 서버에서 완료(`completed`) 처리된 비율(현재 상태 기준). 대화가 없으면 `—` |
| 진행 턴 | 위 대화에서 서버에 저장된 턴 합계와 대화당 평균. 푸르마는 서버 진행 상태(`turn_count`), 냉장고·구름섬은 저장된 장면 턴(`story_turns`). 같은 요청 ID의 재시도, 실패, 위기 안내로 저장되지 않은 입력은 세지 않음 |
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

그래프에는 키보드로 선택 가능한 수치와 일별 표를 제공한다. 조회 중 이전 기간의 수치를 제거하고, 실패/재시도/빈 상태를 구분한다. 요청 취소·15초 타임아웃으로 이탈 및 무응답을 처리한다.

## 후속 연동

- 총 접속 수·재방문율·엔딩 분포·홍보 반응 등 나머지 지표는 별도 범위다. 기존 전체 조회 API(`/overview` 등)는 전체 관리자용으로 남아 있으며 화면은 작품별 통계 API를 사용한다.
- 감정 분석·워드클라우드·콘텐츠 편집은 이번 범위에서 미구현이다. 새 통계를 위해 채팅 원문을 추가 수집하지 않았다.
- 공개 배포 전 로그인 요청 제한, 서버 로그아웃/토큰 폐기, 운영 계정 발급·비밀키 관리 및 HTTPS 배포 정책 검토. 현재 조회 대시보드는 콘텐츠 변경 API를 추가하지 않는다.

## 파일과 검증

프론트: `features/admin/AdminApp.tsx`, `services/adminClient.ts`, `services/shareEvents.ts`, `services/resultImage.ts`, `services/shareProject.ts`, `features/platform/{Platform,shared,StoryResult}.tsx`, `tests/{admin,shareEvents}.test.ts`.
서버: `api/routes/{admin,events}.py`, `api/deps.py`(`get_dashboard_admin`), `services/{admin_access,project_stats}.py`, `db/models.py`(`AdminProjectAccess`, `ShareEvent`), `scripts/create_admin.py`, `tests/{test_project_stats,test_admin_project_access}.py`.

검증 결과는 작업 완료 보고를 따른다. DB·pycache·Images·.backups·실제 .env는 커밋 대상이 아니다.


### 이번 검증 결과 (2026-11-22)

- 백엔드 `pytest -q` 309개 통과(작품별 집계, 이전/현재 장면 세트 합산, 재시도·위기 안내 제외(푸르마 포함), 기간 필터, 작품 담당자 403, 공유 이벤트 분리·입력 제한). 프론트 테스트 58개·`npm run build` 통과.
- 이전 작업에서 서버 Mock 임시 DB로 공유 링크 진입 → 10장면 완료 → 공유·이미지 저장 → 담당 계정 대시보드 반영을 브라우저로 확인했다. 이번 검토에서는 8000 포트의 기존 서버(공유 API 이전 코드)를 종료하지 못해 브라우저 확인을 다시 하지 않았다.
- 미검증: 실제 Gemini/Qwen 연결 상태, 푸르마 서버 연결 화면의 대시보드 반영(백엔드 테스트로만 검증), 네이티브 공유 시트, 모바일 실기기 이미지 저장, 운영 DB.
