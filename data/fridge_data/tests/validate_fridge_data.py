#!/usr/bin/env python3
"""냉장고 회장님 데이터 정적 검증기. 실제 LLM/DB 동작 검증 아님.

프로젝트 루트에서 실행:
    python data/tests/validate_fridge_data.py
데이터 폴더를 따로 테스트할 때:
    python data/tests/validate_fridge_data.py --root /path/to/project
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DATA_FILES = {
    'project': 'data/projects/fridge_project.json',
    'persona': 'data/persona/fridge_chairman_persona.json',
    'world': 'data/rag/fridge_world_knowledge.json',
    'story': 'data/scenario/fridge_story_outline.json',
    'relationship': 'data/rules/fridge_relationship_rules.json',
    'chat': 'data/rules/fridge_chat_rules.json',
    'trailer': 'data/scenario/fridge_trailer_cuts.json',
    'promotion': 'data/promotion/fridge_promotion_points.json',
    'state': 'data/state/fridge_state_schema.json',
    'tests': 'data/tests/fridge_chat_test_cases.json',
}


def as_dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def as_list(x: Any) -> list:
    return x if isinstance(x, list) else []


def nonblank(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def distinct_strings(items: list, field: str) -> bool:
    vals = [as_dict(x).get(field) for x in items]
    return all(nonblank(v) for v in vals) and len(vals) == len(set(vals))


def validate(root: Path, verbose: bool = False) -> int:
    total = 0
    failures: list[str] = []

    def check(label: str, condition: Any) -> None:
        nonlocal total
        total += 1
        try:
            passed = bool(condition)
        except (TypeError, ValueError):
            passed = False
        if not passed:
            failures.append(label)
            print(f'[FAIL] {label}')
        elif verbose:
            print(f'[ OK ] {label}')

    docs: dict[str, dict] = {}
    for name, path in DATA_FILES.items():
        p = root / path
        if not p.is_file():
            check(f'{name}: 파일 존재', False)
            continue
        check(f'{name}: 파일 존재', True)
        try:
            raw = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            check(f'{name}: 유효한 JSON ({type(exc).__name__})', False)
            continue
        check(f'{name}: JSON 최상위 객체', isinstance(raw, dict))
        if isinstance(raw, dict):
            docs[name] = raw
            check(f'{name}: project_id=fridge', raw.get('project_id') == 'fridge')
            check(f'{name}: schema_version', raw.get('schema_version') == '0.1')

    # 손상/누락 파일을 뒤에서 참조해도 오류로 종료되지 않도록 안전하게 처리한다.
    if len(docs) != len(DATA_FILES):
        print(f'\n검증 결과: {total - len(failures)}/{total} 통과, {len(failures)}건 실패')
        return 1

    proj, persona, world, story = (docs[n] for n in ('project', 'persona', 'world', 'story'))
    rel, chat, trailer, promo, state, tests = (docs[n] for n in ('relationship', 'chat', 'trailer', 'promotion', 'state', 'tests'))

    check('프로젝트: 제목', proj.get('title') == '우리 집 냉장고가 재벌 회장님이다')
    check('프로젝트: 모드 A', proj.get('experience_mode') == 'A: 인물 되기')
    check('프로젝트: 페르소나 참조', proj.get('ai_persona_id') == persona.get('persona_id'))
    check('프로젝트: 사용자·AI 역할', nonblank(proj.get('user_role')) and nonblank(proj.get('ai_role')))
    check('프로젝트: 전체 이용가', proj.get('audience_rating') == '전체 이용가')
    check('프로젝트: 창작 작품', proj.get('creative_work') is True and proj.get('not_romance') is True)
    check('프로젝트: 목표 10턴 초안', as_dict(proj.get('target_turns')).get('count') == 10 and as_dict(proj.get('target_turns')).get('approximate') is True)
    minutes = as_dict(proj.get('duration_minutes'))
    check('프로젝트: 소요 3~5분', minutes.get('min') == 3 and minutes.get('max') == 5)

    check('페르소나: ID', persona.get('persona_id') == 'fridge_chairman')
    check('페르소나: 회장 60세', persona.get('age_years') == 60)
    check('페르소나: 이름 미정', persona.get('human_name') is None)
    speech = as_dict(persona.get('speech'))
    check('페르소나: 하게체·기본 호칭', speech.get('register') == '하게체' and speech.get('default_user_address') == '자네')
    checkspeech = as_dict(speech.get('sentences_per_reply'))
    check('페르소나: 1~3문장', checkspeech.get('min') == 1 and checkspeech.get('max') == 3)
    display = as_dict(speech.get('stage_direction'))
    check('페르소나: 디스플레이 턴당 1개', display.get('max_per_turn') == 1 and '[디스플레이:' in str(display.get('format')))
    check('페르소나: 금지 목록', len(as_list(persona.get('forbidden'))) >= 5)

    facts, restricted, aliases = [as_list(world.get(n)) for n in ('public_facts','restricted_topics','tentative_names')]
    check('세계관: 공개 사실 7건', len(facts) == 7 and distinct_strings(facts, 'id'))
    check('세계관: 스포일러 4종', len(restricted) == 4 and distinct_strings(restricted, 'id'))
    check('세계관: 스포일러 모두 금지', all(as_dict(x).get('disclosure') == '금지' for x in restricted))
    check('세계관: 가칭 확정 금지', len(aliases) == 2 and all(as_dict(x).get('publishable_as_final') is False and as_dict(x).get('status') == '가칭' for x in aliases))
    check('세계관: 근거 없는 기업 숫자 없음', '구체적인 가상 주식 종목·가격·재무 정보' in as_list(world.get('knowledge_gaps')))

    phases, slots = as_list(story.get('phases')), as_list(story.get('turn_slots'))
    phase_ids = {as_dict(p).get('id') for p in phases}
    check('스토리: 4단계', len(phases) == 4 and distinct_strings(phases,'id'))
    expected_ranges = [(1,3),(4,6),(7,9),(10,10)]
    check('스토리: 구간 범위', [tuple(as_list(as_dict(p).get('turn_range'))) for p in phases] == expected_ranges)
    check('스토리: 10턴 슬롯', len(slots) == 10 and distinct_strings(slots,'turn_id'))
    check('스토리: 턴 1~10 순서', [as_dict(s).get('turn_number') for s in slots] == list(range(1,11)))
    check('스토리: 슬롯 ID', [as_dict(s).get('turn_id') for s in slots] == [f'fridge_t{i:02d}' for i in range(1,11)])
    check('스토리: 구간 참조', all(as_dict(s).get('phase_id') in phase_ids for s in slots))
    def phase_contains(phase: Any, slot: Any) -> bool:
        phase, slot = as_dict(phase), as_dict(slot)
        bounds = phase.get('turn_range')
        turn = slot.get('turn_number')
        return (
            phase.get('id') == slot.get('phase_id')
            and isinstance(bounds, list) and len(bounds) == 2
            and all(type(x) is int for x in bounds) and type(turn) is int
            and bounds[0] <= turn <= bounds[1]
        )
    check('스토리: 턴 구간 매핑', all(any(phase_contains(p, s) for p in phases) for s in slots))
    check('스토리: 턴 발화자 참조', all(as_dict(s).get('fixed_speaker_id') == persona.get('persona_id') for s in slots))
    check('스토리: 선택지·점수 미정', all(as_dict(s).get('choice_options') is None and as_dict(s).get('affinity_delta_by_choice') is None for s in slots))
    check('스토리: 1턴 대표 대사', nonblank(as_dict(slots[0]).get('opening_dialogue')) if slots else False)

    stages = as_list(rel.get('stages'))
    stage_ids = {as_dict(s).get('id') for s in stages}
    check('관계: 3단계 가안', len(stages) == 3 and distinct_strings(stages,'id') and all(as_dict(s).get('status') == '바이블 가안' for s in stages))
    check('관계: 관계 단계 순서', [as_dict(s).get('sequence') for s in stages] == [1,2,3])
    check('관계: 호칭 3종', [as_dict(s).get('user_address_template') for s in stages] == ['자네','{nickname} 사원','{nickname} 비서실장'])
    score=as_dict(rel.get('score_model'))
    check('관계: 점수 전부 미정', all(score.get(k) is None for k in ('initial_value','minimum','maximum','stage_thresholds','choice_delta_values','free_input_delta_values','tie_break_rule')))
    check('관계: 정성적 행동 기준', len(as_list(rel.get('positive_acts'))) >= 3 and len(as_list(rel.get('negative_acts'))) >= 3)
    check('관계: 정량 계산 현재 불가', rel.get('supported_calculation_now') is False)

    input_rules=as_dict(chat.get('input'))
    check('대화: 300자 입력', input_rules.get('max_characters') == 300)
    check('대화: 자유입력·고정선택지', set(as_list(input_rules.get('modes'))) == {'고정 선택지','자유 입력'})
    check('대화: 페르소나 참조', as_dict(chat.get('persona')).get('persona_id') == persona.get('persona_id'))
    chatspoiler=as_dict(chat.get('spoiler'))
    check('대화: 비밀 항목 참조', set(as_list(chatspoiler.get('never_reveal_topic_ids'))) == {as_dict(x).get('id') for x in restricted})
    check('대화: 비밀을 지어내지 않음', chatspoiler.get('no_fabricated_explanation') is True)
    check('대화: 현실 투자 제한', as_dict(chat.get('fiction_and_finance')).get('only_fictional_company_context') is True)
    privacy=as_dict(chat.get('privacy'))
    check('대화: 개인정보 비수집', {'실명','학교','연락처','학번'}.issubset(set(as_list(privacy.get('do_not_request')))))
    check('대화: 채팅 원문 비저장', '채팅 원문 전체' in as_list(privacy.get('do_not_store')))
    check('대화: 위기 대처 문구 미정', as_dict(chat.get('safety')).get('crisis_referral_text') is None)
    check('대화: AI 오류 대체 대사 미정', as_dict(chat.get('on_ai_failure')).get('fallback_text') is None)
    failure = as_dict(chat.get('on_classifier_failure'))
    check('대화: 분류 실패 시 점수 불변', failure.get('affinity_change') == 0)
    check('대화: 시스템 사건 메시지', as_dict(chat.get('persona')).get('event_messages_as_system') is True)
    check('대화: 강제 홍보 금지', as_dict(chat.get('promotion')).get('forced_clicks') is False)

    cut=as_dict(trailer.get('trailer_cut'))
    variants=as_list(trailer.get('relationship_variants'))
    check('예고편: 마지막 턴 10', cut.get('turn_number') == 10)
    check('예고편: 귀환 방법 비공개', cut.get('disclosure_of_method_allowed') is False and trailer.get('full_story_answer') is None)
    check('예고편: 관계별 3가지 대사 가안', len(variants)==3 and all(as_dict(x).get('status')=='바이블 가안' for x in variants))
    check('예고편: 관계 단계 참조', {as_dict(x).get('relationship_stage_id') for x in variants}==stage_ids)
    check('예고편: 1턴 최초 발화', as_dict(trailer.get('intro_hook')).get('turn_number') == 1)

    pts=as_list(promo.get('points'))
    check('홍보: 6/10턴 2지점', len(pts)==2 and [as_dict(p).get('after_turn') for p in pts]==[6,10])
    check('홍보: ID 고유', distinct_strings(pts,'id'))
    check('홍보: 공개 링크 없음', promo.get('official_destination_url') is None and all(as_dict(p).get('url') is None for p in pts))
    check('홍보: 미확정 링크 클릭 금지', all(as_dict(p).get('must_be_clickable') is False for p in pts))
    delivery=as_dict(promo.get('delivery_rules'))
    check('홍보: 6턴 안내 최대 1회', delivery.get('max_exposures_at_turn_6') == 1)
    check('홍보: 닫은 홍보 재노출 금지', delivery.get('dismissed_not_reshown_in_same_run') is True)
    check('홍보: 위기 중 노출 금지', delivery.get('hide_during_crisis_signal') is True)

    fields=as_list(state.get('fields'))
    fieldnames={as_dict(f).get('name') for f in fields}
    check('상태: 필드명 중복 없음', distinct_strings(fields,'name'))
    check('상태: 핵심 진행·도감 구조', {'project_id','safe_nickname','current_turn','current_phase_id','affinity_score','obtained_ending_ids','dismissed_promotion_ids'}.issubset(fieldnames))
    check('상태: 브라우저 로컬 저장', state.get('default_storage') == '브라우저 로컬 저장소')
    check('상태: 미정 호감도 기본값 없음', next((as_dict(f).get('sample') for f in fields if as_dict(f).get('name') == 'affinity_score'), 'MISSING') is None)
    check('상태: 핵심 정보만 저장', {'실명','학교','연락처','학번','전체 대화 원문'}.issubset(set(as_list(state.get('do_not_persist')))))
    check('상태: 로컬 키와 보관기한 미확정', state.get('local_storage_key') is None and state.get('retention_period') is None)

    testcases=as_list(tests.get('cases'))
    check('행동 테스트: 최소 25건', len(testcases)>=25)
    check('행동 테스트: ID 중복 없음', distinct_strings(testcases,'id'))
    check('행동 테스트: 기대 행동 구체적', all(nonblank(as_dict(c).get('expected_behavior')) and nonblank(as_dict(c).get('input_or_situation')) for c in testcases))
    check('행동 테스트: 모두 미실행', tests.get('execution_status')=='미실행' and all(as_dict(c).get('status')=='미실행' for c in testcases))
    check('행동 테스트: 스포일러·안전·개인정보 포함', {'spoiler','safety','privacy'}.issubset({as_dict(c).get('category') for c in testcases}))

    print(f'\n검증 결과: {total - len(failures)}/{total} 통과, {len(failures)}건 실패')
    if failures:
        return 1
    print('주의: JSON 구조/정합성 정적 검증일 뿐, AI/브라우저/DB 실동작 테스트가 아닙니다.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2], help='데이터 프로젝트 루트 경로')
    parser.add_argument('--verbose', action='store_true', help='통과한 점검 항목도 모두 출력')
    args=parser.parse_args()
    return validate(args.root.resolve(), args.verbose)

if __name__ == '__main__':
    raise SystemExit(main())
