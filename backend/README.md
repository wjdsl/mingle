# 개인 실험용 Gemini 연결

기존 설계의 대사 생성 부분만 구현한다. Mock은 서버 없이 동작하며 Gemini도 같은 개강 2턴에서 종료한다. 전체 12턴·분류·RAG·기억·인증·서버 저장·운영용 안전 검출은 구현하지 않았다. 게임 진행은 기존 프론트 reducer가 관리한다. 기존 설계 문서와 프롬프트 초안은 수정하지 않았다.

## 실행

프로젝트 루트에서 Python 3.10 이상을 권장한다.

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

`backend/.env`를 편집기로 열어 `GEMINI_API_KEY`에 본인의 키를 입력한다. 키를 터미널 명령·프론트 코드·VITE 변수에 넣지 않는다. `.env`는 Git 제외 대상이며 프로그램은 키나 제공자 예외 원문을 출력하지 않는다. 기존 `.env`가 있으면 복사로 덮어쓰지 않는다.

`GEMINI_MODEL`과 코드 기본값은 `gemini-3.8-flash`다. 사용 가능한 모델 ID로 변경할 수 있다. 모델 별칭은 제공자에 따라 변경될 수 있다. 설정은 요청마다 읽는다.

`POST /api/chat/turn`의 503은 `backend/.env`에서 읽은 `GEMINI_API_KEY`가 없거나, 빈 값 또는 공백뿐일 때 발생한다. 파일과 항목이 존재하는 것만으로는 충분하지 않다. 편집기에서 실제 키를 입력하고 저장한 뒤 재시도한다. 설정은 요청마다 읽으므로 키 수정만으로 서버를 재시작할 필요는 없다. 이 단계에서는 Gemini API를 호출하지 않으며, 모델·권한·할당량 등 제공자 오류는 502로 처리한다.

```sh
backend/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

다른 터미널에서:

```sh
cd frontend
npm ci
npm run dev
```

Vite가 출력한 로컬 URL을 열어 시작 화면의 `대화 모드`에서 Mock 또는 Gemini를 선택한다. Gemini는 입력과 현재 2턴의 대화 맥락을 Google로 전송하며 API 사용 비용이 발생할 수 있다. 민감한 개인정보는 입력하지 않는다. 완료 화면의 `모드 선택으로 돌아가기`로 모드를 바꾼다. Mock 기본 대사·선택지·`?mockError=once`는 유지한다.

Vite 개발 서버가 `/api`를 127.0.0.1:8000으로 프록시한다. `vite preview`나 정적 배포에는 별도의 동일 출처 프록시가 필요하다. 로컬 실험용으로만 실행한다.

## 계약과 실패 처리

`POST /api/chat/turn`: 기존 requestId, turn(1 또는 2), input에 history를 추가한다. history는 현재 입력 전의 `{role: character | user, text}` 목록이며 1턴 1개, 2턴 3개다. 선택 ID와 문구는 서버에서 턴별 확인한다. history 내용의 진실성까지 검증하는 서버 세션은 없다.

응답은 `{text, emotion}`만 반환한다. emotion은 confused/happy/sparkle로 제한하고 서버와 브라우저에서 검증한다. 시스템 프롬프트는 `prompts/pruma_system.md`를 읽고 2턴 실험의 장면·출력 계약을 별도 지침으로 덧붙인다.

422 입력 오류, 503 설정 누락, 504 제한 시간 초과, 502 제공자·출력 검증 실패를 반환한다. 제공자 예외와 입력 원문은 오류 응답에 포함하지 않는다. UI는 기존 오류/재시도를 사용하며 응답 검증 성공 때만 턴을 한 번 반영한다. 자동 Mock 전환은 없다. 재시도는 같은 requestId와 입력을 사용하지만 서버 캐시가 없으므로 모델을 다시 호출하고 비용이 추가될 수 있다. 요청 중 새로고침·취소도 이미 시작된 제공자 호출의 취소나 과금 취소를 보장하지 않는다.

## 검증

```sh
backend/.venv/bin/python -m pytest backend/tests -q
cd frontend
npm test
npm run build
```

백엔드 테스트는 SDK를 대체하여 입력 검증·프롬프트 적용·출력 enum·설정 누락·시간 초과·오류 비노출을 확인한다. 실제 키·모델 권한·할당량·캐릭터 응답 품질은 실제 Gemini 모드에서 별도 확인해야 한다.

SDK 사용법: [Google 공식 Python SDK 문서](https://googleapis.github.io/python-genai/).

## 502 진단과 안전 로그 (2026-10-27)

설치된 google-genai 1.47.0에서 `response_schema=TurnResponse`를 사용하면
`extra="forbid"`의 `additionalProperties=False`가 API 요청의 `additional_properties`로
전달되어 Google이 `400 INVALID_ARGUMENT` / `Unknown name` / `Cannot find field`로 거절하는 것을 실제 호출로 확인했다.
이 예외는 `main.py`의 일반 예외 처리에서 502로 변환됐다.
API 요청에는 지원되는 `types.Schema`를 별도로 사용하고, 응답은 기존 `TurnResponse`로
빈 대사·길이·감정 enum·추가 필드를 계속 엄격하게 검증한다. SDK/모델/키는 변경하지 않았다.

동일한 키로 모델 조회가 성공했으며 `gemini-flash-latest`의 `generateContent` 지원을 확인했다.
수정 후 생성 요청의 스키마 400은 사라졌으나 두 차례 검증에서는 Google의 503,
마지막 검증에서는 Google의 504가 발생해 실제 대사 생성 성공은 확인하지 못했다.
모델 조회 성공만으로 생성 할당량까지 보장하는 것은 아니다.

Uvicorn 기본 로그에 생성 호출 시도/응답 수신/검증 성공 및 실패 분류를 기록한다.
실패 로그의 `trace`는 서버가 임의 생성한 ID이며, `upstream_http`는 Google의 HTTP 상태다.
예: `category=invalid_request upstream_http=400`, `category=quota upstream_http=429`,
`category=provider_unavailable upstream_http=503`. 마지막 경우 앱 응답은 기존 계약대로 502다.
그 밖에 authentication(401), permission(403), model_not_found(404), provider_timeout(Google 504, 앱 502), network,
timeout(앱 504), output_validation, not_configured(앱 503), internal_error를 구분한다.
분류는 HTTP 상태 기준이므로 상세 원인을 단독으로 확정하지 않는다.
예외 원문·traceback·키·대화·프롬프트·생성 대사·클라이언트 requestId는 로그에 넣지 않는다.
HTTP/SDK debug 로그는 활성화하지 않는다.

코드 변경을 반영하려면 실행 중인 백엔드를 다시 시작한다(`--reload` 사용 시 자동 반영).

이번 검증: 백엔드 27개·프론트 7개 테스트 통과, `git diff --check` 통과.
프론트 빌드는 `tsc` 단계에서 장시간 추가 출력 없이 대기하여 중단했으므로 성공 여부는 미확인이다.
기존 Python 3.9/LibreSSL 및 SDK Pydantic 경고는 남아 있으나,
실제 Google HTTP 오류 응답을 수신했으므로 이번 스키마 400의 원인과는 구분한다.

현재 로컬 Python 3.9.6 환경에서도 대체 SDK 테스트 14개가 통과했다. 다만 Python 지원 종료·LibreSSL·SDK 내부 Pydantic 경고가 있어 실제 API 실험에는 최신 Python 3.11 이상을 권장한다. 테스트 통과가 해당 환경의 실제 HTTPS 호출 성공을 보장하지 않는다.

## 503 재시도 및 안정적인 로컬 검증 (2026-10-31)

- upstream 503만 최대 1회 자동 재시도한다(총 2회). SDK 자체 재시도는 `HttpRetryOptions(attempts=1)`로 끈다. 대기는 1~2초 균등 지터다.
- 개발 진단용으로 개별 SDK HTTP 요청은 60초, 전체 호출·백오프·클라이언트 종료는 125초, 브라우저 요청은 135초 제한을 적용한다. 재시도에 새 전체 제한을 부여하지 않는다. 두 번의 HTTP 요청 120초와 최대 백오프 2초를 포함할 여유를 둔 값이며 최종 서비스 설정이 아니다. 취소/종료 처리와 프로세스 정지까지 엄격한 실시간 상한을 보장하지는 않는다.
- 429=`quota`, 503=`provider_unavailable`, 전송/전체 timeout=`timeout`, upstream 504=`provider_timeout`으로 구분한다. 429·timeout·504·기타 오류는 자동 재시도하지 않는다. 기존 응답 계약(제공자 오류 502, 로컬 timeout 504, 설정 누락 503)은 유지한다. 재시도 로그에는 고정 분류·상태·시도 번호만 기록한다.
- 프론트는 내부 재시도까지 하나의 요청으로 기다리며 `responding` 로딩을 유지한다. 실패 시 pending 입력·history·requestId·메시지·완료 턴을 보존한다. `다시 시도`는 같은 요청을 전송한다. 새로고침하면 메모리 상태는 사라진다. 자동/수동 재시도에는 제공자 비용이 추가될 수 있다.

curl 200(31.4초)은 성공 사례이며 별도 요청의 Google 503과 양립한다. upstream 503 → 앱 502는 기존 오류 계약이다. 파일 변경에 따른 재시작은 진행 중 연결 종료나 응답 지연을 일으킬 수 있으나, Google 503의 원인으로 확정할 근거는 없다.

안정적인 검증은 기존 8000 포트 서버를 해당 터미널에서 종료한 뒤 프로젝트 루트에서 아래 명령으로 서버 하나만 실행한다. **`--reload`와 다중 worker를 사용하지 않는다.** 요청 중 코드 편집·서버 재시작·브라우저 새로고침을 피한다. Vite도 소스 편집에 따른 HMR/새로고침으로 메모리 상태에 영향을 줄 수 있다. `.env`는 요청마다 읽는다.

```sh
backend/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

자동 검증은 위 테스트 명령을 따른다. SDK/fetch를 대체하여 실제 API를 호출하지 않는다. 추가 백엔드 테스트는 503→성공, 연속 503, 429/504/전송 timeout 무재시도, 첫 호출·백오프·두 번째 호출 중 전체 제한을 확인한다. 이번 작업에서는 실제 API 및 실행 중 서버 재시작 실험은 수행하지 않았다.

이번 변경 검증: 백엔드 36개·프론트 8개 테스트 통과, `git diff --check` 통과. Python 3.9 지원 종료·LibreSSL·SDK Pydantic 경고 4개는 기존 환경에 남아 있다. 프론트 빌드는 `tsc` 단계에서 장시간 출력 없이 대기하여 중단했으며, 빌드 성공은 확인하지 못했다. 브라우저 실화면·실제 API·서버 재시작 중 요청 검증은 미수행이다.

## 2026-11-01 개발 진단 설정

`backend/.env`와 예시·코드 기본 모델을 `gemini-3.8-flash`로 명시했다. 기존 GenerateContent API와 설치된 google-genai 1.47.0을 유지하며 Thinking 설정은 추가하지 않았다. 의존성 설치·업데이트는 수행하지 않았다.

이번 변경에서는 실제 Gemini API를 호출하지 않았다. 별도 실제 호출 검증이 필요한 항목:
- 해당 모델 ID의 존재·계정 접근 권한·할당량과 GenerateContent/JSON 스키마 지원.
- 대사·감정 응답 품질과 푸르마 페르소나 및 2턴 맥락 유지.
- 실제 503 이후 재시도 성공, 실제 네트워크 지연에서 60/125/135초 제한 동작.
- 브라우저에서 실패 후 같은 요청 재시도와 메시지·턴 중복 방지.

이번 검증: 백엔드 전체 36개·프론트 전체 9개 테스트와 TypeScript `tsc --noEmit --diagnostics`, `git diff --check` 통과. SDK 대체 테스트로 503 최대 1회 재시도·1~2초 지터·60초 HTTP 설정·125초 전체 제한 및 각 단계 취소를 확인했고, fetch/reducer 테스트로 135초 설정·동일 요청 재전송·상태 보존·중복 방지·2턴 종료를 확인했다. 기존 Python 3.9/LibreSSL/Pydantic 경고 4개는 유지된다. `npm run build` 및 Vite 직접 빌드는 장시간 대기 후 중단했다(종료 코드 130). Vite 빌드 시작 로그까지는 확인했으나 완료는 확인하지 못했다. macOS `dataless` 상태 의존성 파일이 관측됐으며 빌드 지연의 단독 원인으로 확정하지 않는다. 실제 API 및 브라우저 실화면 검증은 미수행이다.

## 2026-11-01 실제 호출 진단과 로컬 모델 변경

사용자 승인으로 실제 API를 9회 호출했다(생성 6회, 모델 조회·목록 3회). 키·요청·응답 원문은 로그에 남기지 않고 상태·소요 시간만 기록했다. 최소 생성은 "OK라고만 답해." 한 문장, SDK 60초 제한, 재시도 없이 실행했다.

| 모델 | 요청 | 결과 |
|---|---|---|
| gemini-3.8-flash | 모델 조회 | 200 (0.40초) |
| gemini-3.8-flash | 최소 생성 | Google 504 DEADLINE_EXCEEDED (58.94초) |
| gemini-flash-latest | 최소 생성 | Google 504 DEADLINE_EXCEEDED (58.94초) |
| gemini-2.5-flash | 모델 조회 / 최소 생성 | 200 / 404 NOT_FOUND (0.40초) |
| (전체) | generateContent 지원 모델 목록 | 200, 46개 |
| gemini-3.7-flash | 최소 생성 | Google 503 UNAVAILABLE (6.24초) |
| gemini-3.5-flash | 최소 생성 | 200 (5.21초), 응답 `model_version`은 gemini-3.6-flash, thoughts 103토큰 |
| gemini-3.5-flash | 기존 백엔드 `/api/chat/turn` 1턴(선택지 `map`) | 200 (9.40초), `{text, emotion}` 검증 통과 |

판단: 최소 요청에서도 3.8·3.7이 실패하고 같은 코드·키로 3.5가 성공했으므로, 이번 503·504는 프롬프트·스키마·SDK·Python·네트워크가 아니라 해당 모델의 제공자 측 혼잡으로 본다. 504가 60초 직전에 발생한 것은 SDK가 붙이는 `X-Server-Timeout: 60` 기한과 일치하며 지연의 원인은 아니다. 모델 목록에 있어도 생성이 가능하다는 보장은 없다(2.5-flash 404). 설치된 SDK 1.47.0의 `ThinkingConfig`에는 `thinking_level`이 없고 `thinking_budget`만 있다.

조치: 로컬 `backend/.env`의 `GEMINI_MODEL`만 `gemini-3.5-flash`로 변경했다. 코드 기본값·`.env.example`·프롬프트·스키마·timeout·재시도는 유지했다. 이 ID는 제공자 측에서 다른 버전으로 라우팅될 수 있으며 팀 공통 모델 결정이 아니다. 성공은 1회 확인이며 안정성, 브라우저 2턴 전체 진행, 3.8 대비 페르소나 품질은 미확인이다. 3.8 혼잡이 해소되면 같은 최소 요청으로 다시 비교한다.

## 2026-11-01 선택적 LOW Thinking (로컬 실험용)

`backend/.env`에 아래 항목을 두면 생성 요청에 LOW Thinking을 전달한다. 항목이 없거나 빈 값이면 기존과 동일하게 모델 기본 Thinking을 사용한다(요청 본문·헤더·제한 시간 동일). 허용 값은 `low`뿐이며(앞뒤 공백·대소문자 무시) 그 밖의 값은 SDK 클라이언트를 만들기 전에 설정 오류로 처리한다. 앱 응답은 503과 `GEMINI_THINKING_LEVEL` 안내 메시지이고, 로그 분류는 `invalid_setting`이다. `.env`는 요청마다 읽으므로 서버 재시작 없이 반영된다.

```sh
GEMINI_THINKING_LEVEL=low
```

팀 공통 설정이 아니다. `.env.example`과 코드 기본값은 변경하지 않았으며, 현재 로컬 `.env`에만 `GEMINI_MODEL=gemini-3.5-flash`와 함께 설정했다.

**SDK 1.47.0 우회 경로:** 설치된 google-genai 1.47.0의 `ThinkingConfig`에는 `thinking_level`이 없다(`thinking_budget`만 있음). 그래서 요청별 `GenerateContentConfig.http_options=HttpOptions(extra_body={"generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}})`로 REST 필드를 직접 보낸다. SDK는 요청 본문을 만든 뒤 `extra_body`를 재귀 병합하므로 `responseMimeType`·`responseSchema`는 유지되고, 요청별 옵션에 없는 timeout(60초)·재시도(1회)는 클라이언트 설정을 그대로 사용한다. 이 내용은 실제 SDK가 만든 최종 HTTP 요청을 전송 직전에 가로채는 테스트로 확인했다. 공식 필드가 아닌 우회 경로이므로 SDK를 올릴 때 `ThinkingConfig(thinking_level=...)`로 바꿀지 다시 검토한다.

**실험 결과 (gemini-3.5-flash, 응답 `model_version`은 모두 gemini-3.6-flash, 재시도 없음):**

| 조건 | 성공 | 1턴 응답 시간 | 2턴 응답 시간 | 전체 중앙값 / 최댓값 | Thinking 토큰 |
|---|---|---|---|---|---|
| 기본값 | 3/4 (503 1회) | 5.68, 3.59초 | 4.01초 | 4.01 / 5.68초 | 386~484 |
| LOW | 4/4 | 1.61, 1.67초 | 2.09, 1.88초 | 1.77 / 2.09초 | 보고 없음 |

별도 1회 탐색에서도 기본값 4.79초, `thinking_budget=512` 2.75초, LOW 1.75초였다. 응답을 받은 경우 JSON 검증은 모두 통과했고 호칭·존댓말·장면 지시·1→2턴 연결은 두 조건 모두 유지됐다.

**한계:** LOW에서 2턴 `인사하고 들어가자`를 선택했을 때 망설이다 "선배 말대로" 조용히 뒷문으로 들어가는 응답이 1건 나왔다(선택과 반대 행동). 같은 입력의 기본값 응답은 503으로 받지 못해 LOW 때문인지 판단하지 못했다. 장면 지시(조용히 입장)와 충돌하는 선택지에서 발생할 수 있다. 또 2턴 지시문의 "시연" 표현을 대사에 그대로 쓰는 경우가 1건 있었다. 표본은 조건별 4회로 통계적 결론이 아니며, LOW가 503을 줄인다는 근거는 없다. 브라우저 1턴에서 기본값이 48.9초 걸린 사례가 있어 응답 지연은 제공자 상태에도 크게 좌우된다.

이번 변경 검증: 백엔드 47개 테스트 통과(실제 API 호출 없음). 추가 테스트는 설정 없음·빈 값과 LOW의 최종 HTTP 본문 비교(Thinking 외 본문·헤더·URL·60초 timeout·`X-Server-Timeout` 동일, 스키마 유지, SDK 시도 1회)와 잘못된 값의 설정 오류(SDK 미생성)를 확인한다. 브라우저에서 LOW 설정으로 진행하는 검증은 미수행이다.
