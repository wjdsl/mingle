"""대시보드 2차 이벤트의 허용 목록 (서버가 검사한다).

- 이벤트 종류: 작품 시작 화면 진입, 체험 시작·완료, 홍보 노출·클릭.
- 홍보 콘텐츠 ID: 작품별 허용 목록. 푸르마는 장면 구간(puruma_scenes.SECTIONS)에 배정된 RAG id 중
  data/rag/pruma_rag_mvp.json에 확인된 URL이 있는 것만. 냉장고·구름섬의 결과 화면 영화관 바로가기는 URL이 정해지지 않아
  비어 있다. URL이 정해지면 여기에 콘텐츠 ID를 추가하면 수집·집계가 바로 동작한다.
"""

from __future__ import annotations

from functools import lru_cache

from app.services.puruma_scenes import SECTIONS
from app.services.puruma_state import promo_info

EVENT_TYPES = ("entry_view", "story_start", "story_complete", "promo_impression", "promo_click")
PROMO_EVENTS = frozenset({"promo_impression", "promo_click"})
VISITOR_EVENTS = frozenset({"story_start", "story_complete"})
# 익명 세션·작품(·콘텐츠)당 한 번만 저장한다.
ONCE_PER_SESSION = frozenset({"entry_view", "promo_impression"})
MAX_EVENTS_PER_HOUR = 60  # 공유 이벤트와 같은 수준

# 냉장고·구름섬 영화관 바로가기: URL 미정(2026-11-22). 정해지면 {"fridge": ("cinema_link",)}처럼 추가한다.
PENDING_PROMOS: dict[str, tuple[str, ...]] = {"fridge": (), "cloud": ()}


@lru_cache(maxsize=1)
def promo_contents() -> dict[str, dict[str, str]]:
    """작품 -> {콘텐츠 ID: 표시 이름}. 이름은 홍보 카드에 보이는 문구(관리자 화면용)."""
    puruma: dict[str, str] = {}
    for section in SECTIONS:
        for promo_id in section.promo_ids:
            info = promo_info(promo_id)
            if info is not None:
                puruma[promo_id] = info.label or info.title or promo_id
    return {"puruma": puruma, **{p: {cid: cid for cid in ids} for p, ids in PENDING_PROMOS.items()}}


def allowed_content(project: str, content_id: str | None) -> bool:
    return content_id is not None and content_id in promo_contents().get(project, {})
