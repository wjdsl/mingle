# mingle

LLM-based persona companion AI using character IP

**밍글(MINGLE)** 은 캐릭터 IP와 LLM 페르소나 AI를 결합한 웹 기반 인터랙티브 홍보 플랫폼입니다.
사용자는 캐릭터와 대화하며 이야기를 진행하고, 그 과정에서 학교·기관·기업의 홍보 콘텐츠를 자연스럽게 접합니다.
일반 사용자는 로그인 없이 이용하며, 관리자만 별도 계정으로 로그인합니다.

## 작품

| 작품 | 진입 경로 | 현재 체험 범위 |
|---|---|---|
| 푸르마와 학교 다니기 | `#/project/puruma` | 개강 2턴 대화, 브라우저 로컬 기억(유저노트), 졸업 카드 샘플 |
| 냉장고 회장님 | `#/project/fridge` | 10턴 장면형 대화 (마지막 장면은 고정 연출) |
| 구름섬 구조대 | `#/project/cloud` | 5명 대원 다중 응답. Mock은 3개 미션, Gemini 모드는 10턴 (결과 카드는 고정 샘플) |

세 작품 모두 기본은 **Mock(정해진 대사)** 으로 동작하고, 환경변수를 지정하면 백엔드를 거쳐 실제 Gemini로 대화합니다.

## 현재 상태

**구현됨**

- MINGLE 홈과 3개 작품의 소개 → 호칭 입력 → 채팅 → 결과 흐름
- 백엔드를 통한 Gemini 연동: 푸르마 `/api/chat`, 냉장고·구름섬 `/api/story-chat`
- Gemini 오류(할당량 초과·일시 장애·시간 초과) 안내와 같은 요청 재시도
- 작품 링크 공유(네이티브 공유 → 클립보드 → 수동 복사). 링크에는 작품 ID만 담습니다.
- 관리자 로그인과 조회 대시보드(`#/admin`)
- 의견 보내기 창(작성·복사까지, 전송 기능은 없음)

**아직 구현되지 않음**

- 관리자 통계와 3개 작품의 연결 (현재 대시보드는 서버 시드 캐릭터 기준)
- 냉장고·구름섬의 새로고침 후 진행 복원
- 엔딩 판정, 엔딩 카드 이미지 저장, 엔딩 도감 획득 기록
- 위기 상황 안내 등 운영용 안전 처리

## 폴더 구조

```text
mingle/
├── frontend/   React 19 + Vite + TypeScript + 일반 CSS
├── backend/    FastAPI + SQLAlchemy, SQLite(기본) 또는 PostgreSQL/pgvector
├── data/       작품별 페르소나·규칙·시나리오·대시보드 데이터(JSON)와 검증 스크립트
├── prompts/    시스템 프롬프트 초안
├── docs/       기획서(SRS), 작품 기획, 데이터·AI·프론트 설계서, 스토리 바이블
└── AGENTS.md   팀원과 AI 코딩 에이전트의 공통 개발 지침
```

## 빠른 시작

### 1. 프론트만 실행 (Mock, 서버·API 키 불필요)

Node.js 22 이상이 필요합니다.

```bash
cd frontend
npm install
npm run dev
```

터미널에 표시된 주소(기본 `http://127.0.0.1:5173`)로 접속합니다. 새로고침하면 진행이 초기화됩니다.

### 2. 백엔드 실행 (API 키 없이 Mock LLM)

Python 3.12 이상이 필요합니다(Docker 이미지는 3.12).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

- API 문서: <http://localhost:8000/docs>
- 헬스체크: <http://localhost:8000/api/health>

### 3. 실제 Gemini로 시연

`backend/.env`에 `GEMINI_API_KEY`를 넣은 뒤, 프론트를 아래 환경변수와 함께 실행합니다. 두 변수는 독립적이라 하나만 지정해도 됩니다.

```bash
cd frontend
VITE_PURUMA_CLIENT=api VITE_STORY_CLIENT=api npm run dev
```

Gemini 호출 횟수를 아끼려면 서버 시작 옵션을 함께 지정해야 합니다. 전체 순서는
[백엔드 가이드의 안전 실행 절차](backend/README.md#2026-11-18-푸르마-기억-시연-실행)를 따릅니다.
Gemini를 호출하지 않고 같은 흐름을 리허설하는 방법도 같은 절에 있습니다.

> API 키는 `backend/.env`에만 넣습니다. 프론트 코드나 `VITE_*` 환경변수에 넣지 않으며, `.env`는 커밋하지 않습니다.

## 테스트

```bash
cd frontend
npm test
npm run build
```

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

백엔드 테스트는 SQLite와 Mock LLM으로 실행되어 외부 API를 호출하지 않습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [AGENTS.md](AGENTS.md) | 팀 공통 개발 지침과 작업 기록 |
| [docs/mingle-srs.md](docs/mingle-srs.md) | 서비스 요구사항 명세 |
| [docs/푸르마_프로젝트_기획서.md](docs/푸르마_프로젝트_기획서.md) | 푸르마 작품 기획 |
| [docs/stories/](docs/stories/) | 냉장고 회장님·구름섬 스토리 바이블과 시나리오 |
| [docs/FRONTEND_DESIGN.md](docs/FRONTEND_DESIGN.md) | 프론트엔드 설계 |
| [docs/AI_LLM_DESIGN.md](docs/AI_LLM_DESIGN.md) | AI·LLM 설계 |
| [docs/Pruma_Data_Design.md](docs/Pruma_Data_Design.md) | 푸르마 데이터·대시보드 설계 |
| [frontend/README.md](frontend/README.md) | 프론트 실행 모드와 구현 기록 |
| [frontend/INTEGRATION_HANDOFF.md](frontend/INTEGRATION_HANDOFF.md) | 프론트·백엔드 통합 지점과 미완료 항목 |
| [frontend/ADMIN_GUIDE.md](frontend/ADMIN_GUIDE.md) | 관리자 계정 발급과 대시보드 |
| [backend/README.md](backend/README.md) | 백엔드 API, 설정, 시연 실행 절차 |

## 협업 규칙

- 지금까지는 `main`에서 작업 브랜치를 만들고 Pull Request로 `main`에 합쳐 왔습니다.
- 작업 전후로 [AGENTS.md](AGENTS.md)의 지침을 확인하고, 기획과 실제 구현을 구분해 기록합니다.
- API 키, 비밀번호, 토큰, 로컬 DB(`*.db`)는 커밋하지 않습니다.
