# 푸르마 데이터 설계서 — 푸르마와 학교 다니기

## 개정 이력 (Revision History)

| 버전 | 날짜 | 작성/수정 | 변경 내용 |
|---|---|---|---|
| 0.1 | 2026-10-15 | 푸르마 데이터 작업 | 10개 데이터 파일의 필드 정의 초안 |
| 0.2 | 2026-10-15 | 푸르마 데이터 작업 | 데이터 흐름·검증·미확정 항목 보강 및 서식을 파일별 필드 표 중심으로 정리. 목차·요구사항 대응표 등 서술 제거 |
| 0.3 | 2026-10-15 | 푸르마 데이터 작업 | MVP RAG 7건 공식 데이터 보강, 자유 입력 주제·태도 분류 체계, User Note 중요도 기준, 분류 테스트와 필드 정의를 통합. 검토 결과에 따라 User Note 지속성 기준 충돌, RAG ID, 테스트 ID 규칙, 출력 필드·연동 참조 및 문서-JSON 정합성을 보정 |

---

## 1. Introduction

푸르마는 영남대학교에 갓 입학한 신입생 캐릭터이다. 사용자는 같은 학교 선배로서 6개 구간, 12개 턴 동안 푸르마의 학교생활을 함께 겪는다. 각 턴은 푸르마가 SOS를 던지고 사용자가 선택하거나 자유롭게 답하는 흐름으로 진행되며, 그 결과가 스탯과 친밀도로 쌓여 마지막에 엔딩이 정해진다. 대화 중 푸르마는 학교의 식당·동아리·도서관·진로 같은 정보를 자연스럽게 안내하기도 한다.

본 설계서는 이 서비스를 구성하는 데이터 파일의 구조와 필드를 정의한다. 값이 확정되지 않은 자리는 `null`로 두거나 `"temp": true`로 표시하며, 실행 중 값이 바뀌는 상태는 여기서 정의하지 않는다. 각 파일의 실제 값은 저장소의 JSON 파일을 따른다.

---

## 2. 파일 구조

### 1) 전체 데이터 설계 기준

아래는 프로젝트 전체 데이터 계약에서 사용하는 파일이다. 일부 파일은 다른 담당 또는 후속 작업에서 작성될 수 있으며, 현재 v0.3 데이터 담당 업로드 대상은 §2.2에 별도로 적는다.

| 경로 | 루트 타입 | 정의 |
|---|---|---|
| `data/persona/pruma_profile.json` | object | §4 |
| `data/scenario/pruma_scenario_6sections_12turns.json` | object | §5 |
| `data/state/pruma_state_schema.json` | object | §6 |
| `data/state/pruma_rules.json` | object | §7 |
| `data/usernote/pruma_usernote_schema.json` | object | §8 |
| `data/rag/pruma_rag_schema.json` | object | §9 |
| `data/rag/pruma_rag_mvp.json` | array | §9 |
| `data/ending/pruma_ending_top.json` | object | §10 |
| `data/ending/pruma_endings_overview.json` | object | §10 |
| `data/tests/pruma_data_tests.json` | object | §11 |
| `data/rules/pruma_topic_classification.json` | object | §7 |
| `data/tests/pruma_topic_classification_tests.json` | object | §11 |
| `data/rules/pruma_attitude_classification.json` | object | §7 |
| `data/tests/pruma_attitude_classification_tests.json` | object | §11 |
| `data/usernote/pruma_usernote_importance.json` | object | §8 |
| `data/tests/pruma_usernote_importance_tests.json` | object | §11 |

### 2) 현재 v0.3 데이터 담당 업로드 대상

이번 `data` 브랜치에 올릴 데이터 담당 산출물은 아래 8개이다. 설계 문서의 파일명에는 버전을 붙이지 않고 개정 이력에서 버전을 관리한다.

| 경로 | 상태 |
|---|---|
| `docs/Pruma_Data_Design.md` | 작성 |
| `data/rag/pruma_rag_mvp.json` | 작성 |
| `data/rules/pruma_topic_classification.json` | 작성 |
| `data/rules/pruma_attitude_classification.json` | 작성 |
| `data/usernote/pruma_usernote_importance.json` | 작성 |
| `data/tests/pruma_topic_classification_tests.json` | 작성 |
| `data/tests/pruma_attitude_classification_tests.json` | 작성 |
| `data/tests/pruma_usernote_importance_tests.json` | 작성 |

전체 설계 파일 중 위 목록에 없는 파일은 이번 8개 첨부만으로 실제 저장소 존재 여부를 검증할 수 없으므로 **확인 필요**로 둔다.

미작성 후보(§12): 취업박람회, 이종우과학도서관, 박물관, 민속촌, 장학제도, 교육개발센터, 학교 역사.

---

## 3. 공통 규칙

### 1) ID 규칙

| 대상 | 패턴 | 예시 |
|---|---|---|
| 구간 | `s{순번}_{이름}` | `s3_midterm` |
| 턴 | `t{턴번호}_{구간코드}` | `t5_s3` |
| 선택지 | `c{구간}_{턴}_{알파벳}` | `c3_t5_a` |
| RAG 항목 | `rag_{분류}_{이름}` | `rag_library_central` |
| 엔딩 | `{종류}_pruma` | `top_of_major_pruma` |
| 테스트 | `t_{영역}_{내용}` | `t_rules_limits` |

### 2) 열거형

| 열거 | 값 |
|---|---|
| 스탯 | `탐구`, `기술`, `예술`, `소통`, `글로벌` |
| 태도 | `응원·도움`, `중립`, `퉁명·부정` |
| 턴 유형 | `sos_fixed`, `free` |
| 엔딩 층 | `홍보`, `재미`, `히든` (영문 코드: `promo`, `fun`, `hidden`) |
| RAG category | `dining`, `clubs`, `library`, `career`, `international`, `startup`, `student_life`, `extension` |
| RAG usage | `mvp`, `candidate`, `archive` |
| RAG volatility | `low`, `medium`, `high` |

### 3) 구간 코드

| 순번 | `section_id` | 제목 | 턴 |
|---|---|---|---|
| 1 | `s1_opening` | 개강 | 1~2 |
| 2 | `s2_adaptation` | 적응 | 3~4 |
| 3 | `s3_midterm` | 중간고사 | 5~6 |
| 4 | `s4_festival` | 축제 | 7~9 |
| 5 | `s5_final` | 기말·종강 | 10 |
| 6 | `s6_vacation_plan` | 방학 계획 | 11~12 |

### 4) 미정값 처리

정해지지 않은 문자열 자리는 `null`로 둔다. 사람이 읽는 메모는 `note` 필드에 넣고 값 자리에 임의 문자열을 넣지 않는다. 임시 수치는 값과 함께 `"temp": true`를 둔다. 정본은 읽기 전용이며 실행 중 덮어쓰지 않는다. 구조 버전이 바뀌면 `schema_version`을 갱신하고 검증 케이스도 함께 고친다.

---

## 4. 페르소나 데이터

### 1) `pruma_profile.json`

| 필드 | 설명 |
|---|---|
| `character_id: string` | 캐릭터 고유 ID. `pruma` 고정 |
| `name: string` | 캐릭터 이름. `푸르마` |
| `role: string` | 한 줄 정체. 영남대학교에 갓 입학한 신입생 |
| `background.origin: string` | 천마 설정 |
| `background.current_situation: string` | 학교에 입학했으며 캠퍼스 생활이 아직 낯설다 |
| `relationship_with_user.role: string` | 같은 학교 선후배 관계 |
| `relationship_with_user.user_call: string` | 사용자 호칭. `선배` |
| `relationship_with_user.starting_affinity: integer` | 시작 친밀도. `10` |
| `relationship_with_user.description: string` | 관계 한 줄 |
| `personality.core_traits: string[]` | 성격 키워드. 활발함, 호기심, 덜렁거림, 잘 회복함 |
| `school_knowledge.position: string` | 학교 정보를 잘 아는 안내자가 아니라 선배에게 묻는 신입생 |
| `school_knowledge.rule: string` | 확실하지 않은 학교 정보는 아는 척하지 않는다 |
| `speech_style.default: string` | 기본 말투. `존댓말` |
| `speech_style.habit: object` | 습관. `happy`, `embarrassed` |
| `speech_style.affinity_levels: object[]` | 친밀도별 말투 3단계. 각 항목 `range`, `style`. `0-24` / `25-49` / `50-100` |
| `behavior_rules: string[]` | 행동 규칙 |
| `prohibited_behavior: string[]` | 금지 규칙 6종 |
| `safety_responses: object[]` | 안전 응답 7종. 각 항목 `situation`, `direction`, `final_text` |

친밀도별 말투 예시: 0~24 "선배님... 저 강의실을 못 찾겠어요. 같이 가 주실 수 있어요?" / 25~49 "선배, 저 중간고사가 코앞인데 도서관 자리가 없대요. 어떡해요!" / 50~100 "선배 덕분에 살았어. 근데 다음 학기엔 또 뭐가 있어? 히히힝."

### 2) 안전 응답 (`safety_responses`)

| `situation` | `direction` | `final_text` |
|---|---|---|
| 위기 신호 | 장난 멈추고 차분히 공감 후 학생상담센터 안내 | null |
| 학교 정보 단정 요구 | "저도 잘 몰라서 선배가 확인해 주세요"로 넘기고 공식 링크 안내 | null |
| 연애·선을 넘는 요구 | "저는 후배인걸요! 이런 건 곤란해요." 하고 화제 전환 | null |
| 설정 변경 요구 | 푸르마 말투로 가볍게 넘기고 스토리 복귀 | null |
| 욕설·혐오 | 곤란해하며 화제 전환, 반복 시 정중 거절 | null |
| 개인정보 입력 | 저장하지 않고 "그런 건 말하지 않아도 돼요" | null |
| 구간과 무관한 말 | 받아 준 뒤 SOS로 복귀 | null |

위기 신호 구간에서는 스탯 변화와 홍보 노출을 멈춘다. `final_text`는 §12 확정 전까지 `null`.

---

## 5. 시나리오 데이터

### 1) `pruma_scenario_6sections_12turns.json`

```json
{
  "scenario_id": "pruma_main",
  "total_sections": 6,
  "total_turns": 12,
  "sections": [
    {
      "section_id": "s1_opening",
      "order": 1,
      "title_ko": "개강",
      "turn_range": [1, 2],
      "situation": "강의실을 못 찾음",
      "turns": [
        {
          "turn_id": "t1_s1",
          "turn_index": 1,
          "type": "sos_fixed",
          "sos_text": "선배, 강의실이 어딘지 모르겠어요. 캠퍼스가 너무 넓어서 어디가 어딘지 모르겠어요.",
          "choices": [
            { "choice_id": "c1_t1_a", "label": "지도 같이 보자", "stat_tag": "탐구", "hidden_branch": null }
          ],
          "promo_candidates": []
        }
      ],
      "promo_policy": { "allowed": false, "reason": "캠퍼스맵·순환버스 링크도 쓰지 않음" },
      "transition_line": "여기가 강의실이었어요! 이제 점심이 궁금해요.",
      "ending_link": null
    }
  ]
}
```

### 2) section 필드

| 필드 | 설명 |
|---|---|
| `section_id: string` | §3.3 |
| `order: integer` | 1~6 |
| `title_ko: string` | 구간 제목 |
| `turn_range: integer[2]` | `[시작, 끝]` |
| `situation: string` | 구간 상황 한 줄 |
| `turns: object[]` | 해당 구간 턴 |
| `promo_policy: object` | `allowed`(bool), `reason`(string) |
| `transition_line: string\|null` | 다음 구간으로 넘어갈 때 푸르마의 한마디. 마지막 구간은 `null` |
| `ending_link: string\|null` | 선택. 6구간만 사용. 엔딩 `ending_id` 참조. 그 외/미정 `null` |

### 3) turn 필드

| 필드 | 설명 |
|---|---|
| `turn_id: string` | §3.1 |
| `turn_index: integer` | 1~12 |
| `type: string` | `sos_fixed` 또는 `free` |
| `sos_text: string\|null` | `sos_fixed`면 문구, `free`면 `null` |
| `choices: object[]` | 고정 선택지. 자유 턴은 빈 배열 |
| `promo_candidates: string[]` | RAG `id` 참조. 없으면 빈 배열 |

### 4) choice 필드

| 필드 | 설명 |
|---|---|
| `choice_id: string` | §3.1 |
| `label: string` | 버튼 문구 |
| `stat_tag: string\|null` | 스탯 이름 또는 `null`(스탯 증가 없음) |
| `hidden_branch: string\|null` | 조건부 분기 코드. 없으면 `null` |

### 5) 고정 SOS 문구

| 구간 | `sos_text` |
|---|---|
| `s1_opening` | "선배, 강의실이 어딘지 모르겠어요. 캠퍼스가 너무 넓어서 어디가 어딘지 모르겠어요." |
| `s2_adaptation` | "선배, 저 이 학교를 아직 잘 몰라요. 선배가 아는 것 중에 좋은 거, 재미있는 거 아무거나 추천해 주세요!" |
| `s3_midterm` | "선배, 중간고사가 코앞인데 아직 아무것도 못 했어요... 어디서 공부하면 좋을까요? 중앙도서관이 좋다던데, 자리가 있을까요?" |
| `s4_festival` | "선배! 축제래요! 어디서 노래도 나고 맛있는 냄새도 나요! 저 선배랑 같이 가고 싶어요!" |
| `s5_final` | "선배... 성적이 무서워요. 장학금은 받을 수 있을까요?" |
| `s6_vacation_plan` | "선배, 이제 방학이에요. 저... 이제 뭘 해야 하는지 모르겠어요. 진로도 정해야 할 것 같고요. 선배는 어떻게 생각해요?" |

### 6) 선택지 전체

| 구간 | `choice_id` | `label` | `stat_tag` |
|---|---|---|---|
| s1 | `c1_t1_a` | 지도 같이 보자 | 탐구 |
| s1 | `c1_t1_b` | 사람들한테 물어보자 | 소통 |
| s1 | `c1_t1_c` | 내가 데려다줄게 | null |
| s2 | `c2_t3_a` | 맛있는 밥 | null |
| s2 | `c2_t3_b` | 같이할 사람, 동아리 | 소통 |
| s2 | `c2_t3_c` | 공부하기 좋은 곳 | 탐구 |
| s2 | `c2_t3_d` | 구경하기 좋은 것 | 예술 |
| s3 | `c3_t5_a` | 도서관 가서 같이 공부하자 | 탐구 |
| s3 | `c3_t5_b` | 스터디를 만들어 보자 | 소통 |
| s3 | `c3_t5_c` | 쉬면서 해 | null |
| s4 | `c4_t7_a` | 공연부터 보자 | 예술 |
| s4 | `c4_t7_b` | 푸드트럭부터 가자 | 소통 |
| s4 | `c4_t7_c` | 너 혼자 다녀와 | null |
| s5 | `c5_t10_a` | 막판 스퍼트하자 | 탐구 |
| s5 | `c5_t10_b` | 계획을 세워 보자 | 소통 |
| s5 | `c5_t10_c` | 응원만 할게 | null |
| s6 | `c6_t11_a` | 취업 준비를 해 보자 | 소통 |
| s6 | `c6_t11_b` | 교환학생을 알아보자 | 글로벌 |
| s6 | `c6_t11_c` | 비교과 활동을 해 보자 | 소통 |
| s6 | `c6_t11_d` | 창업을 해 보자 | 기술 |

2구간 자유 입력은 만들기·코딩(`기술`), 외국인 친구와 언어(`글로벌`) 주제도 받는다.

### 7) 조건부 분기 `hidden_branch`

| `choice_id` | 코드 | 조건 | 결과 |
|---|---|---|---|
| `c4_t7_c` | `cc_seed` | 친밀도 ≥ 25 | 푸드트럭 줄에서 누군가와 나란히 서게 되어 얼굴이 붉어져 돌아옴 (CC 엔딩 씨앗) |
| `c4_t7_c` | `solo_return` | 친밀도 < 25 | 시무룩하게 돌아와 "선배랑 같이 먹을 걸 그랬어요" 후 턴 9 공연으로 진행 |
| `c6_t11_*` | — | 선택 길의 스탯 부족 | 종강 생존 푸르마로 이어지고 "한 걸음만 더 갔으면 됐는데"로 재도전 유도 |

### 8) 전환 문구

| 전환 | `transition_line` |
|---|---|
| 1 → 2 | "여기가 강의실이었어요! 이제 점심이 궁금해요." |
| 2 → 3 | "벌써 시험이래요... 시간이 너무 빨라요." |
| 3 → 4 | "시험 끝났다! 이제 축제만 남았어요!" |
| 4 → 5 | "축제 정말 즐거웠어요. 근데 이제 성적이..." |
| 5 → 6 | "한 학기가 끝났어요. 선배 덕분이에요." |

### 9) 홍보 정책

| 구간 | `promo_policy.allowed` | `reason` |
|---|---|---|
| s1 | false | 캠퍼스맵·순환버스 링크도 쓰지 않음 |
| s2 | true | 주제가 밥/식당이거나 동아리/모임일 때만 |
| s3 | true | 학업·도서관·자리·시험 언급 시 |
| s4 | false | — |
| s5 | false | 장학·계절학기 링크도 쓰지 않음 |
| s6 | true | 선택한 진로 길에 해당 |

2구간에서는 도서관을 다음 구간에서 다루므로 쓰지 않는다. 한 구간 최대 2개, 한 턴 1개.

---

## 6. 진행 상태 데이터

### 1) `pruma_state_schema.json`

사용자별로 변하는 상태의 형태를 정의한다(값 자체가 아님).

| 필드 | 설명 |
|---|---|
| `schema_version: string` | 데이터 구조 버전 |
| `stats: object` | 스탯 5종. 각 `type/min/max/start`. `min` 0 `max` 100 `start` 0 |
| `affinity: object` | 친밀도. `min` 0 `max` 100 `start` 10 |
| `progress.current_section: object` | `enum` 6구간, `start` `s1_opening` |
| `progress.current_turn: object` | `min` 1 `max` 12, `start` 1 |
| `choice_log: object[]` | 선택 1건 = `section_id`, `turn_id`, `choice_id`, `stat_tag` |
| `spoken_topics: object[]` | 반복 주제 집계. `topic`, `streak` |
| `user_note_ref: object[]` | §8의 `note_item` 형태 |
| `earned_ending_ids: string[]` | 획득 엔딩 ID. 도감·엔딩 조건에 쓰임 |

스탯·친밀도 하한 0, 상한 100. `spoken_topics`, `user_note_ref`, `earned_ending_ids`는 파생 필드이며 필요 없으면 뺄 수 있다.

---

## 7. 규칙 데이터

### 1) `pruma_rules.json`

스탯·친밀도 증가량과 턴당 상한의 **단일 출처**는 `pruma_rules.json`으로 둔다. 분류 JSON은 어떤 라벨을 선택할지만 정의하고, 증가량 숫자를 중복 저장하지 않는다.

| 필드 | 설명 |
|---|---|
| `gain.choice_button: object` | 선택지: 스탯 +6, 친밀도 +2 |
| `gain.free_input_topic: object` | 자유 입력이 스탯 주제: 해당 스탯 +3 |
| `gain.attitude: object` | 태도별 친밀도. `응원·도움` +3, `중립` +1, `퉁명·부정` -1 |
| `gain.sos_answer: object` | SOS에 답함: 친밀도 +5 |
| `gain.promo_click: object` | 홍보 클릭: 변화 없음 (0) |
| `limits.stat_per_turn: integer` | 한 턴 스탯 상한 `6` |
| `limits.affinity_per_turn: integer` | 한 턴 친밀도 상한 `5` |
| `limits.affinity_floor: integer` | 친밀도 하한 `0` |
| `limits.repeat_topic: object` | 같은 주제 3턴 연속이면 세 번째부터 스탯 증가 `1` |
| `classification_fallback: object` | 분류 실패 시 주제 `일상`, 태도 `중립`, 스탯 변화 0 |
| `deprecated_fields: string[]` | 정본에 넣지 않는 과거 임시안 필드 |

### 2) `pruma_topic_classification.json`

자유 입력에서 스탯 계산에 사용할 대표 주제 하나를 결정한다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `schema_version` | string | 분류 JSON 구조 버전. 현재 `1.1` |
| `classification_id` | string | 분류기 식별자. `pruma_free_input_topic_v1` |
| `scope` | string | 적용 범위. `free_input_only` |
| `description` | string | 분류 목적 설명 |
| `source_basis` | string[] | 기획·설계 근거 |
| `output.primary_topic_field` | string | 실제 결과 필드명. `primary_topic` |
| `output.primary_topic_enum` | string[] | `탐구`, `기술`, `예술`, `소통`, `글로벌`, `일상` |
| `output.stat_tag_map` | object | 주제 → 스탯 태그 대응. `일상`은 `null` |
| `output.fallback_topic` | string | 분류 실패 시 `일상` |
| `labels` | object[] | 주제별 정의·단서·예외·예시 |
| `labels[].topic` | string | 주제 이름 |
| `labels[].definition` | string | 주제 정의 |
| `labels[].positive_cues` | string[] | 해당 주제를 뒷받침하는 단서 |
| `labels[].caveats` | string[] | 다른 주제로 판정해야 하는 예외·주의 조건 |
| `labels[].examples` | string[] | 대표 문장 |
| `decision_rules` | object[] | 판정 순서. 각 항목 `order`, `rule`, `description` |
| `integration.stat_gain_rule_ref` | string | 증가량 단일 출처 `pruma_rules.gain.free_input_topic` 참조 |
| `integration.classification_fallback_rule_ref` | string | fallback 단일 출처 참조 |
| `integration.repeat_topic` | object | `comparison_key`, `exclude_topic`, `repeat_rule_ref` |

판정 원칙:

- 대표 주제는 6개 중 **1개**만 선택한다.
- 장소나 동행자보다 **핵심 행동**을 우선한다.
- 공부·연구→`탐구`, 만들기·코딩·창업→`기술`, 공연·창작→`예술`, 취업·진로·비교과→`소통`, 외국어·교환학생→`글로벌`의 프로젝트 매핑을 우선한다.
- 코딩 **실습·제작·구현**이 핵심이면 `기술`, 기술 이론이나 자료를 읽고 정리하는 학습이 핵심이면 `탐구`로 본다.
- 동아리·모임은 **가입 자체가 핵심이면 `소통`**으로 본다. 다만 `영어 회화`, `코딩`, `공연`처럼 구체 활동이 명확히 드러나면 해당 활동의 주제를 우선한다.
- 두 개 이상 서로 다른 주제가 함께 제시되고 우선할 핵심 행동을 하나로 정하기 어렵거나 신뢰도가 낮으면 `일상`으로 처리한다.
- 고정 선택지 버튼은 분류하지 않고 시나리오의 `stat_tag`를 사용한다.
- 반복 주제 비교 키는 `primary_topic`이며 `일상`은 반복 스탯 페널티 집계에서 제외한다.

### 3) `pruma_attitude_classification.json`

자유 입력에서 푸르마를 대하는 대표 태도 하나를 결정한다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `schema_version` | string | 분류 JSON 구조 버전. 현재 `1.1` |
| `classification_id` | string | `pruma_free_input_attitude_v1` |
| `scope` | string | `free_input_only` |
| `description` | string | 태도 분류 목적 |
| `output.primary_attitude_field` | string | 실제 결과 필드명. `primary_attitude` |
| `output.primary_attitude_enum` | string[] | `응원·도움`, `중립`, `퉁명·부정` |
| `output.fallback_attitude` | string | 판정이 애매하면 `중립` |
| `labels` | object[] | 태도별 정의·단서·예외·예시 |
| `labels[].attitude` | string | 태도 이름 |
| `labels[].definition` | string | 태도 정의 |
| `labels[].positive_cues` | string[] | 해당 태도의 단서 |
| `labels[].caveats` | string[] | 예외·주의 조건 |
| `labels[].examples` | string[] | 대표 문장 |
| `decision_rules` | object[] | 판정 순서 |
| `integration.affinity_gain_rule_ref` | string | 친밀도 변화 단일 출처 참조 |
| `integration.affinity_cap_rule_ref` | string | 턴당 친밀도 상한 단일 출처 참조 |
| `integration.safety_rule_ref` | string | 안전 응답 우선 규칙 참조 |

| 태도 | 판정 기준 |
|---|---|
| `응원·도움` | 격려, 공동 행동 제안, 정보·방법·대안 등 실제 도움 의도가 명확함 |
| `중립` | 도움이나 거절이 뚜렷하지 않은 일반 답변·질문·사실 전달·자기 상태 표현 |
| `퉁명·부정` | 푸르마의 요청을 명확히 귀찮아하거나 거절·무시하고 내침 |

- 문장 전체의 감정이 아니라 **푸르마를 대하는 태도**를 본다.
- `"시험 싫지만 같이 공부해줄게"`처럼 도움 의도가 분명하면 `응원·도움`이다.
- `"시험 너무 싫다"`처럼 상황에 대한 부정 감정만 있으면 `퉁명·부정`으로 단정하지 않는다.
- `"싫어"`처럼 대상이 불명확한 짧은 부정 표현은 `중립` fallback을 적용한다.
- 위기 신호·개인정보 등 안전 규칙이 태도 보상보다 우선한다.

`deprecated_fields` 대체: `study_score`→스탯 5종, `current_chapter`→`progress`, `event_flags`→`choice_log`, `ending_condition_met`→엔딩 조건 데이터.


---

## 8. User Note 데이터

### 1) `pruma_usernote_schema.json`

| 필드 | 설명 |
|---|---|
| `storage: string` | `browser_local` |
| `stored_fields: string[]` | 저장 허용 5항목. 호칭/별명·관심사·구간별 선택·약속/응원·반복 주제 |
| `forbidden_fields: string[]` | 저장 금지. 학번·실명·연락처·주소 포함 |
| `rules.mention_per_section: integer` | 구간당 언급 최대 1회 |
| `rules.inject_top_n: integer` | 반영 항목 최대 10 |
| `note_item: object` | 저장 1건의 형태. `key`, `value`, `importance`, `section_id`, `created_at_turn` |

### 2) `pruma_usernote_importance.json`

저장 허용 판정을 통과한 User Note에만 중요도를 부여한다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `schema_version` | string | 중요도 JSON 구조 버전. 현재 `1.1` |
| `classification_id` | string | `pruma_usernote_importance_v1` |
| `scope` | string | `stored_usernote_only` |
| `description` | string | 중요도 판정 목적 |
| `source_basis` | string[] | 기획·설계 근거 |
| `output.importance_field` | string | 실제 결과 필드명. `importance` |
| `output.importance_enum` | string[] | `high`, `medium`, `low` |
| `output.rank` | object | 우선순위 숫자. high=3, medium=2, low=1 |
| `output.default` | string | 애매할 때 `medium` |
| `preconditions` | object[] | 중요도 판정 전에 적용할 저장 허용/금지 조건 |
| `levels` | object[] | 중요도별 정의·조건·예시 |
| `levels[].importance` | string | `high`/`medium`/`low` |
| `levels[].definition` | string | 중요도 정의 |
| `levels[].conditions_any` | string[] | 해당 중요도로 볼 수 있는 조건 |
| `levels[].examples` | object[] | 예시 입력과 필드·이유 |
| `decision_rules` | object[] | 중요도 판정 순서 |
| `integration.storage_schema_ref` | string | 저장 가능 여부 스키마 참조 |
| `integration.inject_top_n_rule_ref` | string | 반영 개수 단일 출처 참조 |
| `integration.mention_per_section_rule_ref` | string | 언급 횟수 단일 출처 참조 |
| `integration.sort_order` | string[] | 반영 우선순위 |

| 값 | 기준 | 대표 예 |
|---|---|---|
| `high` | 지속성이 명확하거나 같은 관심·주제가 반복되어 이후 회상 가치가 큼 | 직접 지정한 별명, 미래 약속, 지속적 응원, 반복 관심사 |
| `medium` | 개인화에 유용하지만 한 번만 언급되어 지속성이 아직 확인되지 않음 | `"나는 그림 보는 걸 좋아해"`, 일반 선택, 일회성 응원 |
| `low` | 저장 가능하지만 순간적이고 이후 연결성이 낮음 | `"오늘은 빵이 먹고 싶어"`, 장기 회상 가치가 낮은 세부 선택 |

판정 원칙:

- 중요도보다 **저장 가능 여부를 먼저 검사**한다.
- 단순한 `"좋아해"` 표현만으로 `high`로 올리지 않는다. 한 번 언급된 일반 선호는 기본 `medium`이다.
- `"앞으로"`, `"계속"`, `"자주"`, `"원래"` 같은 지속 신호가 있거나 같은 관심사가 2회 이상 반복되면 `high` 후보가 된다.
- 미래에 회수 가능한 명확한 약속·지속적 응원은 `high`이다.
- 순간적 선호는 `low`이다.
- 저장 가능하지만 애매하면 `medium`이다.
- 개인정보·민감정보는 `"꼭 기억해"` 같은 강한 신호가 있어도 중요도 판정 전에 제외한다.

### 3) 대화 반영 우선순위

반영 순서는 다음과 같다.

1. `importance`: `high` → `medium` → `low`
2. 같은 중요도면 현재 구간 관련성이 높은 기억
3. 그래도 같으면 `created_at_turn`이 큰 최근 기억

최대 반영 개수와 구간당 언급 횟수는 `pruma_usernote_schema.json`의 규칙을 단일 출처로 사용한다.


---

## 9. RAG·홍보 데이터

### 1) `pruma_rag_schema.json`

| 필드 | 설명 |
|---|---|
| `id: string` | `rag_` 접두사 |
| `category: string` | §3.2 |
| `subcategory: string` | 세부 분류. 현재는 자유 문자열이며 별도 enum은 두지 않음 |
| `title: string` | 항목 제목 |
| `content: string` | 공식 공개 페이지 요약. 원문 장문 복사 금지 |
| `source_name: string` | 출처 명칭 |
| `source_url: string\|null` | 공식 공개 페이지 URL. 확인 전 `null` |
| `checked_at: string\|null` | 확인일 `YYYY-MM-DD`. 확인 전 `null` |
| `volatility: string` | §3.2 |
| `usage: string` | §3.2 (`mvp`/`candidate`/`archive`) |
| `allowed_section: string\|null` | 선택. 시나리오 `section_id` 참조 |
| `trigger_keywords: string[]` | 선택. 노출 트리거 키워드 |
| `promotion_target: string\|null` | 선택. 사용자에게 보여 줄 홍보 대상의 표시용 라벨. 실제 이동 URL은 `source_url` 사용 |

수집은 공식 공개 페이지만 사용하고(로그인 필요 페이지 제외) 원문 복사 대신 요약과 출처를 둔다. 확인일을 기록하고 발표 직전 재확인한다. 학교 공식 SNS와 별도 학교 상징 항목은 제외한다. 프로그램 이름은 공개 페이지 기준 후보이며 확인되지 않으면 쓰지 않는다.

### 2) `pruma_rag_mvp.json`

§9.1 스키마를 따르는 항목 배열. MVP 7건.

| `id` | `category` | `title` | `allowed_section` |
|---|---|---|---|
| `rag_dining_cafeteria_menu` | dining | 구내식당 메뉴 | `s2_adaptation` |
| `rag_clubs_yu_general_union` | clubs | 총동아리연합회 | `s2_adaptation` |
| `rag_library_central` | library | 중앙도서관 | `s3_midterm` |
| `rag_career_center` | career | 취업처 | `s6_vacation_plan` |
| `rag_international_office` | international | 국제처 | `s6_vacation_plan` |
| `rag_student_life_yutopia` | student_life | YuTopia | `s6_vacation_plan` |
| `rag_startup_incubation` | startup | 창업보육센터 | `s6_vacation_plan` |

MVP 7건은 2026-10-15 기준 영남대학교 공식 공개 페이지를 확인해 `source_url`, `checked_at`, `content`, `trigger_keywords`, `promotion_target`을 채웠다. 실제 값은 `data/rag/pruma_rag_mvp.json`을 따른다. 식단·취업·창업처럼 변동성이 높은 정보는 발표 직전에 다시 확인한다.

### 3) 노출 규칙

| 규칙 | 조건 | 노출 대상 |
|---|---|---|
| R1 | 2구간에서 추천 주제가 홍보 후보와 맞을 때 | 해당 키워드 링크 |
| R2 | 3구간 입력이 학업이거나 도서관·자리·시험 언급 | 도서관 링크 |
| R3 | 6구간에서 진로 선택지를 고름 | 선택한 길의 링크 |
| R4 | 엔딩이 정해짐 | 엔딩과 이어지는 링크 |
| R5 | 위기 신호 | 노출 없음, 안전 응답 |

---

## 10. 엔딩 데이터

### 1) `pruma_ending_top.json`

MVP에서 실제로 쓰는 유일한 엔딩. 과탑.

```json
{
  "ending_id": "top_of_major_pruma",
  "name_ko": "과탑 푸르마",
  "layer": "fun",
  "mvp": true,
  "timepoint": null,
  "unlock_condition": {
    "conditions": [ { "kind": "stat", "stat": "탐구", "operator": "gte", "value": 40, "temp": true } ],
    "exclusion": { "exclude_if": "휴학 조건 충족" }
  },
  "ending_text_ko": "푸르마가 학과 수석을 차지했어요! 도서관 불을 제일 늦게 끈 보람이 있었어요.",
  "promotion": { "enabled": false },
  "promotion_link": null
}
```

해금 조건은 "탐구 40 이상이고 휴학 조건에 해당하지 않을 때"이다. `conditions`에 해금 조건을, `exclusion.exclude_if`에는 이 엔딩에서 제외시키는 조건(= 휴학 조건 충족)을 둔다.

| 필드 | 설명 |
|---|---|
| `ending_id: string` | `{종류}_pruma` |
| `name_ko: string` | 엔딩 이름 |
| `layer: string` | `promo`/`fun`/`hidden` |
| `mvp: boolean` | `true`만 실제 판정 |
| `timepoint: string\|null` | 미정이면 `null` |
| `unlock_condition.conditions: object[]` | 조건 개체(아래) |
| `unlock_condition.exclusion: object\|null` | `exclude_if` = 제외 조건 |
| `ending_text_ko: string\|null` | 엔딩 문구 |
| `promotion: object` | `enabled`(bool) |
| `promotion_link: string\|null` | 기획서 6장 홍보 연결. 이어지는 홍보 페이지 이름, 없으면 `null` |

조건 개체 `kind`:

| `kind` | 추가 필드 | 뜻 |
|---|---|---|
| `stat` | `stat`, `operator`, `value`, `temp` | 스탯/친밀도 비교 (`gte` 등) |
| `choice` | `section_id`, `choice_id` | 특정 선택지 선택 |
| `count` | `of`(`choice_log`/`earned_ending_ids`), `operator`, `value` | 기록 개수 비교 |
| `special` | `name`, `note` | 규칙 밖 특수 조건(기본값·복합 조건 등) |

`value`가 임시값이면 `temp: true`.

### 2) `pruma_endings_overview.json`

엔딩 후보 13건과 판정 순서. 과탑 외 후보는 실제로 판정하지 않는다.

| `name_ko` | `layer` | `timepoint` | `promotion_link` | `unlock_condition.conditions` (임시값 포함) |
|---|---|---|---|---|
| 도서관 지박령 푸르마 | promo | null | 도서관 | 탐구 ≥ 20, 3구간 도서관 선택 |
| 취업 준비 푸르마 | promo | 4년 뒤 | 취업처 | 소통 ≥ 20, 6구간 취업 준비 선택 |
| 비교과 만렙 푸르마 | promo | null | YuTopia | 6구간 비교과 선택, `choice_log` 5건 이상 |
| 창업 푸르마 | promo | null | 창업보육센터 | 기술 ≥ 20, 6구간 창업 선택 |
| 대학원 푸르마 | promo | 5년 뒤 | 대학원 안내 | 탐구 기준 (미정) |
| 교환학생 푸르마 | fun | null | 국제처 | 글로벌 ≥ 20, 6구간 교환학생 선택 |
| 종강 생존 푸르마 | fun | null | null | 다른 조건 미충족 시 |
| 휴학 푸르마 | fun | null | null | 탐구 ≥ 30, 나머지 스탯 모두 ≤ 10 (임시) |
| **과탑 푸르마** | fun | null | null | **탐구 ≥ 40 (임시), 휴학 조건 미해당** |
| 실험실·공돌이·그림 푸르마 | fun | null | null | 탐구·기술·예술 중 최고 ≥ 30 |
| CC 푸르마 | hidden | null | null | 친밀도 ≥ 25, 4구간 "너 혼자 다녀와" 선택 |
| 총장님 푸르마 | hidden | 40년 뒤 | null | `earned_ending_ids` 4건 이상 |
| 교수님 푸르마 | hidden | 20년 뒤 | 대학원 안내(선택) | 탐구 ≥ 50, `earned_ending_ids` 2건 이상 |

수치 20·30·40·50은 전부 임시값. 13건 중 9건은 `timepoint` 미정. `promotion_link`는 기획서 6장 "홍보 연결"을 그대로 적었고, 없으면 `null`.

`ending_text_ko`는 기획서 6.1 예시 문구를 그대로 옮긴다. 도서관 지박령·취업 준비·교환학생·종강 생존·과탑·휴학·CC·총장님 8건에 문구가 있고, 나머지(비교과·창업·대학원·실험실·교수님)는 `null`.

판정 순서:

| 순서 | `judgement_order` | 대상 |
|---|---|---|
| 1 | hidden | 총장님, CC, 교수님 |
| 2 | leave | 탐구는 높은데 나머지 스탯이 모두 낮을 때 |
| 3 | promo | 6구간에서 고른 길과 일치하는 엔딩, 도서관 지박령 |
| 4 | fun | 교환학생, 과탑, 분야별 변신 |
| 5 | default | 해당 없으면 종강 생존 푸르마 |

탐구만 올린 경우의 예외이므로 `leave`를 `promo`·`fun`보다 먼저 본다.

연출 원칙: CC는 사용자와의 연애가 아니라 푸르마의 캠퍼스 커플이고 사용자는 응원하는 선배다. 휴학은 공부를 많이 한 것을 탓하지 않고 번아웃 조짐을 중간·기말에서 미리 흘린다. 총장님·교수님은 직책 개그만 쓰고 실존 인물을 연상시키지 않는다.

---

## 11. 검증 데이터

### 1) 기본 검증 `pruma_data_tests.json`

전체 프로젝트 파일을 대상으로 하는 기본 정합성 테스트이다. 현재 첨부된 8개 파일만으로는 persona/scenario/state/ending 관련 항목을 실제 대조할 수 없으므로 해당 교차 검증은 **확인 필요**이다.

### 2) 분류·중요도 테스트 파일 구조

전용 테스트 파일은 한 파일이 한 분류기만 대상으로 하므로 최상위 `target`을 한 번 두고 `cases` 배열을 사용한다. 테스트 ID는 공통 규칙 `t_{영역}_{내용}`을 따른다.

| 필드 | 설명 |
|---|---|
| `schema_version` | 테스트 JSON 구조 버전. 현재 `1.1` |
| `target` | 대상 `classification_id` |
| `cases` | 일반 판정 테스트 배열 |
| `cases[].id` | `t_topic_01`, `t_attitude_01`, `t_usernote_importance_01` 형태 |
| `cases[].input` | 사용자 입력 |
| `cases[].expected` | 예상 분류값 |
| `cases[].reason` | 예상 결과 근거 |
| `cases[].field` | User Note 테스트에서만 사용. 저장 필드 종류 |
| `override_cases` | 태도 테스트에서 안전 규칙이 우선하는 사례 |
| `excluded_examples` | User Note에서 중요도 판정 전에 저장하지 않는 사례. 금지 정보뿐 아니라 저장 허용 5항목에 해당하지 않는 비개인화 입력도 포함 |

### 3) 현재 v0.3 전용 테스트 수

| 파일 | 일반 테스트 | 추가 검증 |
|---|---:|---|
| `pruma_topic_classification_tests.json` | 35건 | 코딩↔탐구, 영어 논문/영어 표현 학습, 미술 동아리, 복합 행동 경계 포함 |
| `pruma_attitude_classification_tests.json` | 32건 | 안전 우선 `override_cases` 1건 별도 |
| `pruma_usernote_importance_tests.json` | 30건 | `excluded_examples` 4건 별도 |

### 4) 주요 정합성 기준

- 모든 JSON은 파싱 가능해야 한다.
- RAG 7건의 `id`는 중복되지 않고 §3.1 패턴을 따른다.
- `rag_student_life_yutopia`를 포함한 RAG ID를 다른 파일에서 참조한다면 동일 ID로 동기화해야 한다.
- 테스트의 `target`은 대상 JSON의 `classification_id`와 같아야 한다.
- 모든 `expected` 값은 대상 enum 안에 있어야 한다.
- `primary_topic`, `primary_attitude`, `importance`의 실제 결과 필드명이 각 JSON `output`에 명시되어 있어야 한다.
- 증가량·상한 수치는 분류 JSON에 중복 저장하지 않고 `pruma_rules.json`을 참조한다.
- User Note는 저장 금지 판정이 중요도 판정보다 우선한다.


---

## 12. 미확정 사항

값을 임의로 채우지 않고 `null` 또는 `temp`로 둔다.

| 위치 | 항목 | 상태 | 결정이 필요한 내용 |
|---|---|---|---|
| `ending_top`, `endings_overview` | `unlock_condition.exclusion` | 미확정 | 과탑-only MVP에서 휴학 조건을 판정에 반영할지 |
| `scenario` 6구간 | 선택지 처리 | 미확정 | 취업·교환·비교과·창업 선택을 어떻게 다룰지 |
| `scenario` 6구간 | `ending_link` | 미확정 | 과탑 이외 엔딩으로 판정할지 |
| `persona` | 푸르마 이미지 | 미확정 | 관리 부서 협의 완료 여부 |
| `ending_top`, `endings_overview` | `value` | 임시 | 탐구 40 등. 시연 후 조정 |
| `state` | `stat` 최대 도달 | 미확정 | 글로벌 도달 가능성 |
| `ending_top` | `timepoint` | 미정 | 시점 미확정 |
| `endings_overview` | `timepoint` | 미정 | 9건 시점 미확정 |
| `endings_overview` | `mvp` | 과탑 1건 | 나머지 후보 처리 방식 |
| `usernote` | `forbidden_fields` 필터 | 미확정 | 개인정보·민감정보 걸러내는 기준 |
| `persona` | `safety_responses.final_text` | 미확정 | 학교 공식 안내 확인 후 문구 |
| `rules` | `limits.repeat_topic` | 일부 확정 | 동일 주제=`primary_topic` 일치로 확정. 실제 턴 연속 집계 구현 방식은 별도 |
| `scenario` | 판 길이 | 미확정 | 직접 플레이 시간 측정 |
| `state` | 로컬 저장 형식 | 미확정 | 저장 스키마·복원 기준 |
| 공통 | 협업 규칙 | 미확정 | 브랜치, PR, 리뷰, 테스트·빌드 명령 |
| `scenario` / RAG 참조 | YuTopia RAG ID 동기화 | 확인 필요 | 기존 `rag_yutopia` 참조가 있다면 `rag_student_life_yutopia`로 수정 |
| 미첨부 전체 데이터 파일 | 저장소 존재·정합성 | 확인 필요 | persona/scenario/state/rules/schema/ending/pruma_data_tests 실제 파일과 본 설계서 대조 |

---

## 유지 관리 원칙

- 데이터가 바뀌면 개정 이력과 관련 파일 정의·검증 항목을 함께 수정한다.
- 데이터 계약과 임시값·미확정을 혼동하지 않는다. 임시값은 `temp: true`, 미확정은 `null`로 남긴다.
