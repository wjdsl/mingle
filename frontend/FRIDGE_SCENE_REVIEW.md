# 냉장고 신규 기능 구현 기록

2026-11-10. 사용자의 최종 범위: 냉장고만 구현, 공통 신규 기능 보류.

## 분석

로컬은 feature/frontend-ui 기반 React 19/Vite/TypeScript/일반 CSS이며 해시 작품 라우팅 + History API 단계 이동, 메모리 상태를 사용한다. 로컬 루트 README/AGENTS/FRONTEND_DESIGN, 원격 main의 PM 스토리 바이블·Pruma_Data_Design·백엔드 admin/deps/schema/config를 확인했다. 원격 main의 설계서는 docs/FRONTEND_DESIGN.md 경로다. 원격 변경 전체 병합은 하지 않았다.

관리자 JWT 로그인·me·overview·trigger 조회는 원격 백엔드에 존재한다. get_current_admin은 JWT와 활성 계정을 확인하지만 프로젝트 범위 검사는 확인되지 않았다. 따라서 프로젝트별 서버 인가는 후속 확인/구현이 필요하다. 기존 admin 라우트는 조회 중심이며 콘텐츠 변경 API·피드백 저장 API는 확인하지 못했다. 이번 최종 범위에서 관리자/피드백/GitHub 버튼은 구현하지 않았다.

## 변경 파일

- src/assets/fridge/*.webp: 원격 제공 원화 6개(로비는 미사용).
- src/projects/stories/fridgeStory.ts: 바이블 기반 10턴 Mock 초안과 장면/사건 연결.
- src/projects/stories/catalog.ts: optional sceneImage/event 필드 및 냉장고 데이터 연결/예고편 결과.
- src/features/platform/SceneImage.tsx: 공통 장면 이미지와 확대/로딩/실패 UI.
- src/features/platform/useStoryChat.ts: 호환 메시지 확장 및 장면 시작 메시지 구성.
- src/features/platform/StoryChat.tsx: 메시지별 렌더링, 사건 분리, 예고편 CTA.
- src/features/platform/shared.tsx: 냉장고 포스터/작은 초상 원화 적용.
- src/features/platform/ProjectEntry.tsx: 10턴과 초안 범위 안내.
- src/features/platform/StoryResult.tsx: 기존 하드코딩 설명을 작품 결과 데이터로 연결.
- src/features/platform/platform.css: 이미지/확대창/사건 알림 스타일.
- tests/stories.test.ts: 10턴/사건 순서/비밀 미공개 예고편 경계 검증.
- 루트 AGENTS.md, FRONTEND_DESIGN.md: 실제 범위 추가. 기존 팀 기획 보존.

## 검증

- TypeScript + Vite production build 통과.
- 기존 8개 테스트 통과 후 바이블 경계 테스트 1개 추가; 최종 재실행 결과는 완료 보고 참조.
- 브라우저에서 소개 → 호칭 → 10턴 선택 응답 → 예고편 결과 이동 확인.
- 이미지 로드, 확대 dialog, 닫기와 대화 복귀 확인. 콘솔 오류 없음(초기 조회).
- 360/390/768/1440px 가로 넘침 없음. 장면 이미지 너비 309/320/320/320px. 390×844 로그 높이 470px.
- 로딩 실패/재시도 UI는 구현했으나 실제 네트워크 차단 시뮬레이션은 미실행. 실제 휴대폰 키보드/스크린리더·모든 자유 입력·모든 선택 분기는 미검증.

## 남은 작업

10턴별 대사·선택지 확정, 관계 단계/점수/실제 AI 자유 입력 분류, 개인정보 호칭 판별, 본편 공개 URL, 실제 API와 영구 저장은 후속 범위다. 현재 자유 입력은 내용 분석 없이 고정 응답이다. 원화의 출처·사용 권한은 제공팀 확인 대상이며 새 이미지 생성/외부 다운로드는 없다. 커밋/푸시 없음.
