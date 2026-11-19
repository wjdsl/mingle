# mingle

**밍글(MINGLE)** 은 캐릭터 IP와 LLM 페르소나 AI를 결합한 웹 기반 인터랙티브 홍보 플랫폼입니다.
사용자는 캐릭터와 대화하며 이야기를 진행하고, 그 과정에서 학교, 기관, 기업의 홍보 콘텐츠를 자연스럽게 접하게 됩니다.
일반 사용자는 로그인 없이 이용할 수 있습니다. 관리자는 별도 계정으로 로그인합니다.

## 작품

| 작품 | 경로 |
|---|---|
| 푸르마와 학교 다니기 | `#/project/puruma` |
| 냉장고 회장님 | `#/project/fridge` |
| 구름섬 구조대 | `#/project/cloud` |

기본 실행은 Mock 대화입니다. 설정에 따라 백엔드를 거쳐 Gemini와 대화할 수 있습니다. 푸르마와 냉장고·구름섬의 API 모드는 각각 설정합니다.

## 기술 스택

- 프론트엔드: React, Vite, TypeScript
- 백엔드: FastAPI, SQLAlchemy
- AI: Google Gemini

## 폴더 구조

```text
mingle/
├── frontend/   React + Vite + TypeScript
├── backend/    FastAPI + SQLAlchemy
├── data/       작품별 페르소나·시나리오·대시보드 데이터
├── prompts/    시스템 프롬프트 초안
├── docs/       기획서, 설계서, 스토리 바이블
└── AGENTS.md   공통 개발 지침
```

## 실행

프론트엔드만 Mock 모드로 실행합니다. API 키는 필요하지 않습니다. 설치 기준 환경은 Node.js 22.15.1입니다.

```bash
cd frontend
npm install
npm run dev
```

백엔드와 Gemini 연동 방법은 [backend/README.md](backend/README.md)를 참고하세요.
API 키는 `backend/.env`에 설정하고 커밋하지 않습니다.

관리자 화면은 `#/admin`에서 접근합니다. 서버 실행과 관리자 계정 발급 방법은 [frontend/ADMIN_GUIDE.md](frontend/ADMIN_GUIDE.md)를 참고하세요.

## 문서

- [AGENTS.md](AGENTS.md): 공통 개발 지침과 작업 기록
- [docs/](docs/): 기획서, 프론트엔드·AI·데이터 설계서, 스토리 바이블
- [frontend/README.md](frontend/README.md): 프론트엔드 실행 모드
- [backend/README.md](backend/README.md): 백엔드 API와 설정
