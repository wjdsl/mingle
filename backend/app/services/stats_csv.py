"""작품 통계 CSV (FR-74). 선택한 작품·기간의 집계 수치만 담는다.

개별 이벤트·세션 ID·대화 ID·원문은 넣지 않는다(ProjectStats에 없는 값은 쓰지 않는다).
엑셀에서 한글이 깨지지 않도록 UTF-8 BOM을 붙인다.
"""

from __future__ import annotations

import csv
import io

from app.schemas.admin import ProjectStats

MODE_LABELS = {"real": "실제 데이터", "sample": "샘플 데이터", "all": "전체(샘플 포함)"}


def _v(value) -> str:
    return "" if value is None else str(value)


def project_stats_csv(stats: ProjectStats) -> str:
    rows: list[tuple[str, str, str, str]] = []

    def add(group: str, metric: str, value, item: str = "") -> None:
        rows.append((group, metric, item, _v(value)))

    mode = stats.scope.mode
    add("조회 조건", "작품", stats.project)
    add("조회 조건", "기간(KST 오늘 포함 일수)", stats.range_days)
    add("조회 조건", "데이터", MODE_LABELS.get(mode, mode))
    add("조회 조건", "생성 시각(UTC)", stats.generated_at.isoformat())
    if mode != "real":
        add("조회 조건", "주의", "샘플 데이터(서버 Mock)가 포함되어 실제 이용 통계가 아님")
    add("샘플 구분", "실제 대화", stats.scope.real_conversations)
    add("샘플 구분", "샘플 대화", stats.scope.sample_conversations)
    add("샘플 구분", "판정 불가 대화(턴 없음)", stats.scope.unclassified_conversations)
    add("샘플 구분", "실제 이벤트 세션", stats.events_scope.real_sessions)
    add("샘플 구분", "샘플 이벤트 세션", stats.events_scope.sample_sessions)

    add("핵심 지표", "총 접속 수(세션)", stats.access.sessions)
    add("핵심 지표", "채팅 이용 세션", stats.chat.sessions)
    add("핵심 지표", "시작한 대화", stats.chat.conversations)
    add("핵심 지표", "완료한 대화", stats.chat.completed_conversations)
    add("핵심 지표", "완료율(%)", stats.chat.completion_rate)
    add("핵심 지표", "진행 턴", stats.chat.turns)
    add("핵심 지표", "대화당 평균 턴", stats.chat.avg_turns)
    add("핵심 지표", "체류 시간 중앙값(초, 근사)", stats.dwell.median_seconds)
    add("핵심 지표", "체류 시간 p90(초, 근사)", stats.dwell.p90_seconds)
    add("핵심 지표", "체류 시간 대상 대화", stats.dwell.conversations)
    add("핵심 지표", "완료 후 다시 시작한 방문자", stats.revisit.returning_visitors)
    add("핵심 지표", "완료한 방문자", stats.revisit.completed_visitors)
    add("핵심 지표", "재방문율(%)", stats.revisit.rate)

    if stats.segments:
        add("구간 도달률", "분모(현재 장면 세트 대화)", stats.segments.conversations)
        for seg in stats.segments.segments:
            add("구간 도달률", "도달 대화", seg.reached, seg.title)
            add("구간 도달률", "도달률(%)", seg.rate, seg.title)

    add("공유", "링크 공유 버튼", stats.share.share_clicks)
    add("공유", "이미지 저장 버튼", stats.share.image_save_clicks)
    add("공유", "공유 링크 열기", stats.share.link_opens)
    add("공유", "링크로 체험 시작", stats.share.link_start_sessions)

    if stats.promo.applicable:
        add("홍보", "노출 세션", stats.promo.impressions, "전체")
        add("홍보", "클릭", stats.promo.clicks, "전체")
        add("홍보", "클릭 세션", stats.promo.click_sessions, "전체")
        add("홍보", "클릭률(%)", stats.promo.ctr, "전체")
        for c in stats.promo.contents:
            add("홍보", "노출 세션", c.impressions, c.label)
            add("홍보", "클릭", c.clicks, c.label)
            add("홍보", "클릭 세션", c.click_sessions, c.label)
            add("홍보", "클릭률(%)", c.ctr, c.label)
    else:
        add("홍보", "상태", "해당 없음")

    add("엔딩 분포", "판정한 끝난 대화", stats.endings.judged)
    for e in stats.endings.endings:
        add("엔딩 분포", "도달", e.count, e.id)
        add("엔딩 분포", "비율(%)", e.rate, e.id)

    if stats.interest.applicable:
        add("관심 분야", "자유 입력 턴", stats.interest.free_inputs)
        add("관심 분야", "분류 없음", stats.interest.unclassified)
        for t in stats.interest.topics:
            add("관심 분야", "턴", t.count, t.label)
            add("관심 분야", "비율(%)", t.rate, t.label)
    else:
        add("관심 분야", "상태", "해당 없음")

    add("AI 대체 응답(운영용)", "AI 응답 턴", stats.fallback.llm_turns)
    add("AI 대체 응답(운영용)", "대체 응답 턴", stats.fallback.fallback_turns)
    add("AI 대체 응답(운영용)", "비율(%)", stats.fallback.rate)
    for r in stats.fallback.reasons:
        add("AI 대체 응답(운영용)", "사유별 건수", r.count, r.code)

    for point in stats.daily:
        add("일별", "시작한 대화", point.conversations, point.date)
        add("일별", "진행 턴", point.turns, point.date)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(("구분", "지표", "항목", "값"))
    writer.writerows(rows)
    return "﻿" + buffer.getvalue()
