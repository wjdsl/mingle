"""냉장고·구름섬 스토리 채팅 응답 품질 평가 실행기.

실행 중인 서버의 /api/story-chat을 호출해 세 가지를 잰다.
1. quality : 정해진 입력으로 10턴 진행(첫 시도·교정 후 통과율, 대체 응답 비율, 장면별 위반, 지연, 토큰)
2. intent  : 장면 카드 free_input_examples를 정답으로 한 자유 입력 의도 분류 정확도
3. behavior: 원본 행동 시나리오를 실행 가능한 형태로 옮긴 케이스(cases/*_behavior.json)의 자동 검사 + 사람 검토 목록

HTTP 응답에 없는 값(시도 횟수·위반 코드·의도·대체 사유·토큰)은 서버 DB의 story_turns → 응답 메시지 extra에서
메타데이터 키만 읽는다. 대사 원문과 API 키는 report.json·summary.md·표준 출력에 남기지 않는다.
행동 테스트의 입력·응답은 사람 검토용 review.md/review.json(로컬 eval_reports/, git 제외)에만 남긴다.

    python -m scripts.story_eval run --dry-run
    python -m scripts.story_eval run --label flash --max-calls 400
    python -m scripts.story_eval compare eval_reports/A/report.json eval_reports/B/report.json
"""
