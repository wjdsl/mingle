"""냉장고·구름섬 위기 신호 처리 (기획 초안: docs/stories/safety-notice-and-name-check.md 1장).

사용자의 자유 입력에 자신을 해치려는 표현이 있으면 LLM을 부르지 않고, 장면을 진행하지 않고, 입력 원문을
저장하지 않는다. 안내 말풍선(109·119)은 화면이 그리고, 서버는 `safety_notice` 신호와 캐릭터의 짧은 곁말만 준다.

- 판단이 애매하면 안내하는 쪽을 택한다(공백을 모두 제거하고 포함 여부만 본다).
- 일반적인 힘든 이야기(면접 탈락, 지침 등)는 여기서 걸리지 않고 장면 카드대로 진행한다.
- 안내 문구와 번호는 팀 확정 전 초안이므로 문구는 프론트 `storySafety.ts`에 한 곳으로 모아 두었다.
"""

from __future__ import annotations

import re

from app.services.chat_service import PURUMA_CRISIS_REPLY
from app.services.memory import PURUMA_CRISIS_PATTERNS, is_crisis_text

SAFETY_PROVIDER = "safety"
SAFETY_MODEL = "crisis-notice-v1"

# 푸르마 기억 처리와 같은 단일 목록(memory.py)을 쓴다. 띄어쓰기 변형(죽고 싶 / 죽고싶)도 함께 잡는다.
CRISIS_PATTERNS: tuple[str, ...] = PURUMA_CRISIS_PATTERNS


def is_story_crisis(text: str) -> bool:
    return is_crisis_text(text)


# 안내 뒤 캐릭터 반응: 장난·홍보·진행 없이 곁에 있어 주는 말만. 진단·약속·저장 약속·다음 장면 유도 금지.
COMPANION_LINES: dict[str, tuple[str, str]] = {
    "fridge": ("냉장고 회장", "…자네, 그 번호로 꼭 이야기해 보게. 나는 여기 있겠네."),
    "cloud": ("나나", "…말해 줘서 고마워. 위에 있는 번호, 꼭 눌러 봐."),
    # 푸르마는 /api/chat 위기 응답과 같은 고정 문장을 쓴다.
    "puruma": ("푸르마", PURUMA_CRISIS_REPLY),
}
