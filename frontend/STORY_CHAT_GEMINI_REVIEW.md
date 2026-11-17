# 냉장고·구름섬 Gemini 연동 검증 기록 (2026-11-15)

브랜치 `feature/gemini-story-fridge-cloud` (origin/main@103d05a 기반). 커밋·푸시·PR 없음.

## 실행한 검증

- 백엔드 pytest: 38개 통과(기존 27 + 신규 `tests/test_story_chat.py` 11). SQLite 임시 DB + Mock/가짜 Gemini 공급자.
  - Mock 공급자 응답은 `provider=mock`, `model=mock-story-v1`로 표시
  - 같은 request_id 재시도 → `replayed:true`, 메시지 수 불변 / LLM 실패(502) 시 저장 없음 → 같은 request_id 재시도 성공 시 메시지 2개
  - turn 불일치 409, 다른 장면 선택지 422, 마지막 장면 후 409·대화 completed
  - 가짜 Gemini: provider/model/latency 반환, 시스템 프롬프트에 장면 카드·말투·입력 불신 규칙, 이전 장면 맥락 포함, 연락처 마스킹
  - 구름섬: 알 수 없는 화자 제외·최대 3명, 성향 점수/결과 판정 금지 문구 포함
  - 서버 장면 문장과 프론트 catalog 일치(실제로 1건 불일치를 발견해 수정)
- 프론트: `npm run build` 통과, `npm test` 20개 통과(기존 13 + 신규 `tests/storyApi.test.ts` 7). 빌드 산출물에 키·`x-goog` 문자열 없음.
- HTTP 스모크(`scripts/smoke_story_chat.py --expect-provider mock`, 백엔드 Mock 공급자): 냉장고·구름섬 각 2턴 + 재시도 replay, 저장 메시지 4개.
- 브라우저(VITE_STORY_CLIENT=api, 백엔드 Mock 공급자): 냉장고 호칭 입력 → 선택지 응답에 'AI 미연결 · 서버 고정 응답' 표시 → 다음 장면 → 백엔드 중지 상태에서 자유 입력 실패·오류 표시 → 백엔드 재시작 후 다시 시도 성공. 화면 사용자 메시지 1개, 서버 messages 4개·story_turns 2개.

## 실제 Gemini 검증 (2026-11-15, 사용자가 backend/.env에 키 추가 후)

- 서버: `LLM_PROVIDER=gemini`, `GEMINI_CHAT_MODEL=gemini-3.5-flash`, 별도 임시 SQLite, 시드 끔. 시작 시 Gemini 확인(embed+generate) 통과, `/api/health` `degraded:false`. 키는 `x-goog-api-key` 헤더로 전송되며 서버 로그에서 키 문자열 0건.
- `python -m scripts.smoke_story_chat`(provider가 gemini가 아니면 실패) → 성공(exit 0).

| 작품 | 장면 | provider | model | latency_ms |
|---|---|---|---|---|
| 냉장고 | 1 (선택지) | gemini | gemini-3.5-flash | 5146 |
| 냉장고 | 2 (자유 입력, 현실 주식 질문 포함) | gemini | gemini-3.5-flash | 10801 |
| 구름섬 | 1 (선택지) | gemini | gemini-3.5-flash | 11198 |
| 구름섬 | 2 (자유 입력) | gemini | gemini-3.5-flash | 11563 |

- 같은 request_id 재시도 → `replayed:true`, 대화별 저장 메시지 4개(중복 없음).
- 관찰: 냉장고는 디스플레이 지문 1개 + 하게체, 현실 주식 질문을 "내 정보는 이 냉장고 안에서만 통하네"로 돌림. 구름섬은 2~3명 반말 대사, 두두는 짧은 말·호칭 미사용.
- 브라우저(VITE_STORY_CLIENT=api): 구름섬 미션 1 선택지 → 비비·키키·두두 3개 말풍선, `data-provider=gemini`, Mock 표시 없음, '미션 1/3 · 완료'.
- 주의: 응답 지연 5~12초. 구름섬 1회 응답에서 비비가 '안경'을 올리는 지문(바이블은 고글)처럼 세부 설정이 어긋날 수 있다. 샘플 4~5회 관찰이며 품질·규칙 준수의 통계적 검증은 아니다.

## 실행하지 못한 검증

- 냉장고 10장면·구름섬 3미션 전 구간의 실제 Gemini 진행, 스포일러 유도·프롬프트 공격 등 적대적 입력 평가.
- 서버 시작 시 Gemini 확인 실패 → Mock 자동 대체(기존 `ensure_llm_ready`)는 그대로다. 이 경우 응답 provider가 mock으로 표시되며 실제 연동 성공이 아니다.
- 모바일 실기기, PostgreSQL, 동시 요청 경합(IntegrityError 경로)은 실측하지 않았다(코드상 처리만).
- 로컬 실행 메모: 저장소가 iCloud 동기화 폴더(~/Documents)에 있어 저장소 안 venv/__pycache__/소스 읽기가 멈추거나 Errno 89로 실패했다. 검증은 scratchpad의 venv와 소스 복사본에서 실행했다.
