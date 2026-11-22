# MINGLE Gemini 모델 벤치마크

같은 합성 대화를 두 Gemini 모델에 보내고, 사람이 모델명을 가린 응답을 채점합니다. macOS·Linux, Python 3.10 이상과 표준 라이브러리만 사용합니다. 서비스 서버, DB, Google SDK, GPU를 띄울 필요가 없습니다.

## 현재 상태

2026-11-22에 1단계 구축과 2단계 실연결 확인을 마쳤습니다. 모델당 실제 생성 1건과 읽기 전용 메타데이터 조회 1건을 수행했습니다. 최종 검토에서 v2의 전체 dry-run과 Mock 108건을 완료했습니다. v2 실제 전체 평가와 모델 선정은 대기 중입니다. 측정값은 [연결 검증 및 분석 양식](analysis.md)에 기록했습니다.

| 파일 | 용도 |
|---|---|
| experiment_plan.md | 가설, 통제 변수, 채점 기준과 한계 |
| test_cases.json | 단일 24문항, 작품별 10턴씩 총 30문항(고정 컷 2문항 포함) |
| prompt_context.json, freeze_context.py | 고정한 바이블·세계관·장면 지시와 재생성 도구 |
| run_benchmark.py | 요청 수 예고, 드라이런, Mock·실제 실행, 한도 관리·재개 |
| evaluate.py | JSON 내보내기, 블라인드 채점지, 지표 집계·비교표 |
| test_benchmark.py | 네트워크 없는 회귀 테스트 |
| results/.gitkeep | 결과 디렉터리. 실행 장부·원시 응답·평가지는 로컬에 보관 |
| probe_report.json | 실제 연결 검증 2건의 응답, 요청 SHA-256, 모델 메타데이터 |
| analysis.md | 연결 검증 관측, 실패 분석 및 모델 선정 기록 |

## 기준 저장소

기준은 wjdsl/mingle의 origin/main 커밋 `cceb218`입니다. FastAPI 라우트는 backend/app/api/routes 아래에 있으며 chat과 story_chat이 서로 다른 대화 경로를 씁니다. 서비스는 HTTPX로 Gemini REST v1beta를 호출합니다. 원래 개발 환경의 HTTPX는 0.28.1이며 Google Gen AI SDK는 설치되어 있지 않았습니다. 실험도 같은 REST 모델 ID·생성 API를 사용하며 서비스의 재시도나 Mock 전환은 거치지 않습니다.

냉장고·구름섬의 캐릭터와 장면은 docs/stories, data/{fridge,cloud}_data, backend/app/prompts의 템플릿과 story_prompt.py에서 확인했습니다. 푸르마의 시스템 지침 초안은 prompts/pruma_system.md에 있고 개강 실행 설정은 backend/app/db/seed_puruma.py에 있습니다. 신규 인물 모드를 찾지 못해 승인된 푸르마 대체안을 사용합니다. 3~10턴의 출처와 한계는 [실험 계획](experiment_plan.md)에 기록했습니다.

일반 채팅의 chat_service.py, memory.py, persona_prompt.py는 이전 메시지·기억·검색 자료를 골라 프롬프트를 구성합니다. 서버 DB 기억 경로와 푸르마 브라우저 로컬 노트 경로가 있습니다. 로컬 노트는 서버에서 재검사한 뒤 최대 10개를 반영합니다. 실험은 오직 test_cases.json의 합성 노트와 고정 검색 자료만 읽습니다.

기준 main에는 colab/mingle_qwen_demo.ipynb가 있습니다. experiments/qwen-qlora는 원격 experiment/qwen-qlora 브랜치의 cf556fe에서 확인했습니다. EXP-001은 Colab T4 환경 구성과 모델 로딩까지 기록했으며 학습 결과는 없습니다. 실험 코드는 Qwen 경로를 참조하지 않습니다.

## 로컬 검증

저장소 루트에서 실험 폴더로 이동합니다. 아래 python3은 3.10 이상을 가리켜야 합니다.

```bash
cd experiments/gemini-benchmark
python3 -m unittest -v
python3 run_benchmark.py --mode dry-run --phase full
python3 run_benchmark.py --mode mock --phase full
python3 evaluate.py --mode mock --phase full
```

기본 명령은 dry-run/probe입니다. dry-run은 결과 파일을 만들거나 네트워크를 사용하지 않습니다. Mock 응답에는 [MOCK]가 붙으며 results/mock에만 기록합니다. 고정 설정을 다시 추출하려면 기준 커밋에서 python3 freeze_context.py를 실행해 변경 여부를 대조할 수 있습니다.

## 실제 연결 기록

Phase 2의 두 응답과 측정값은 [v1 원본 기록](probe_report.json)에 보관합니다. 현재 코드와 테스트셋은 `mingle-bench-v2`입니다. 기존 v1 실행과 섞이지 않도록 별도 실행 버전으로 기록합니다. v1 장부를 다시 내보낼 때는 커밋 `f2f83dd`의 평가기와 테스트셋을 사용하고, v2 전체 실행에서는 같은 로컬 장부의 `full` 단계로 이어서 저장할 수 있습니다.

### 연결 확인을 별도로 진행할 때

키는 GEMINI_API_KEY 환경변수 또는 기존 backend/.env에서만 읽습니다. 키 파일을 복제하거나 셸에서 source할 필요가 없습니다. 분리된 Git 작업 폴더에서는 --env-file에 원래 작업 폴더의 절대 경로를 지정합니다. 환경변수를 이미 설정했다면 --env-file을 생략합니다.

```bash
python3 run_benchmark.py --mode metadata --env-file ../../backend/.env
python3 run_benchmark.py --mode live --phase probe --confirm-free-tier --env-file ../../backend/.env
python3 evaluate.py --mode live --phase probe
```

metadata는 두 모델의 정확한 ID·generateContent 지원 여부·토큰 상한을 조회합니다. 둘 중 하나라도 실패하면 원인을 확인합니다. 결제 등급과 프로젝트별 RPM/RPD/TPM은 메타데이터에서 알 수 없습니다. --confirm-free-tier는 같은 키의 현재 AI Studio 프로젝트가 무료임을 실행자가 확인했다는 표시입니다. 승인 당시 값은 실험 계획에 있습니다. 유료 등급이거나 확인할 수 없으면 live를 실행하지 않습니다. [현재 프로젝트 한도](https://aistudio.google.com/rate-limit)

## 전체 실행과 여러 날에 걸친 재개

아래 명령은 **실제 요청 108건의 별도 실험**을 시작합니다. 모델당 생성 품질 52건과 고정 컷 복제 진단 2건입니다. 재개할 때도 같은 버전·프로젝트 키·결과 폴더에서 같은 명령을 씁니다.

```bash
python3 run_benchmark.py --mode live --phase full --confirm-free-tier --env-file ../../backend/.env
python3 evaluate.py --mode live --phase full
```

- probe와 full은 별도 표본입니다. 한도 장부는 공유합니다. --max-calls N은 두 모델을 합친 이번 프로세스의 신규 시도 수를 제한합니다. 실험 도중에도 evaluate.py로 현재까지 저장한 결과를 내보낼 수 있습니다.
- 모델별 RPM 간격을 두고 최근 60초의 보수적인 입력 바이트 예산과 일일 요청 수를 확인합니다. 로컬 RPD에 도달하면 종료 코드 2로 멈춥니다. 태평양 시간 자정 이후 같은 명령으로 재개합니다. 다른 앱에서 쓴 양은 Google이 집계합니다.
- HTTP 429를 기록하면 즉시 종료합니다. 같은 장부에서는 당일 프로세스를 다시 실행해도 추가 요청을 보내지 않습니다. 다음 할당일에 **이미 거절된 429 문항까지** 다시 시도하려면 전체 실행 명령에 --retry-quota를 추가합니다. 이전 오류도 장부와 오류율에 남습니다. 자동 반복이나 모델 교체는 없습니다.
- SQLite에 전송 예약을 먼저 커밋하고 한 프로세스만 실행하도록 잠급니다. Ctrl-C, 타임아웃 등으로 결과가 불명확한 요청은 자동으로 다시 보내지 않습니다. 해당 문항은 미평가로 남고, 멀티턴이면 같은 모델·작품의 뒷부분도 제외합니다. 독립 문항은 이어서 진행합니다. raw 요청을 정확히 한 번 처리했는지는 클라이언트만으로 증명할 수 없습니다.
- 원장 results/live/runs.sqlite3을 보존합니다. 복수 작업 폴더·컴퓨터에서 따로 시작하면 중복 방지와 로컬 할당량 이력이 공유되지 않습니다. 이동 시 실행을 중지하고 results/live 전체를 함께 옮깁니다.

## 평가

evaluate.py는 선택한 모드와 단계의 results/{mode}/{phase}/에 다음 파일을 만듭니다.

1. responses.json에서 요청 본문, 실행 시각(UTC), 설정, 모델 버전, 답변·오류·토큰을 확인합니다.
2. 평가자에게 reviews.json만 제공합니다. 문항별 네 점수·추가 위반·심각한 위반·근거를 기록한 뒤 저장합니다. 적용 불가는 "N/A", 미검토는 null입니다.
3. 같은 evaluate.py 명령을 다시 실행합니다. 기존 점수를 유지하고 summary.json과 comparison.md를 갱신합니다. summary.json에는 문항별 점수, 자동 위반, 지표별 유효 쌍 수, 고정 컷 복제 진단이 있습니다. 고정 컷 응답은 블라인드 채점지와 생성 품질 총점에서 제외합니다.
4. 실제 전체 실행의 채점이 끝나면 analysis.md에 실패 사례와 선정 근거를 작성합니다. Mock·probe에는 최종 총점을 내지 않습니다.

검증한 기존 명령은 backend/에서 python -m pytest -q, frontend/에서 npm test와 npm run build입니다.
