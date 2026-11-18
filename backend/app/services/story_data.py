"""냉장고·구름섬 스토리 데이터 읽기 전용 로더.

- 공식 데이터(팀원 정본): data/fridge_data/{persona,rules,rag,scenario/fridge_trailer_cuts}…,
  data/cloud_data/{persona,rules,rag}… — 읽기만 하고 수정·보완하지 않는다.
- 초안 데이터(AI 담당 추출본): data/{fridge,cloud}_data/scenario/*_scene_cards_draft.json
  (docs/stories/*-scenario.md 장면 카드 원문 추출, 팀 미확정).
- 데이터 위치: 환경변수 STORY_DATA_DIR(없으면 저장소 루트의 data/). 백엔드만 배포되는 환경에서는
  경로가 없을 수 있으며, 이때 load_* 함수는 None을 돌려주고 호출부가 대체 경로를 쓴다.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_DATA = Path(__file__).resolve().parents[3] / "data"

OFFICIAL_FILES: dict[str, dict[str, str]] = {
    "fridge": {
        "persona": "fridge_data/persona/fridge_chairman_persona.json",
        "chat_rules": "fridge_data/rules/fridge_chat_rules.json",
        "world": "fridge_data/rag/fridge_world_knowledge.json",
        "trailer": "fridge_data/scenario/fridge_trailer_cuts.json",
    },
    "cloud": {
        "personas": "cloud_data/persona/cloud_personas.json",
        "chat_rules": "cloud_data/rules/cloud_chat_rules.json",
        "world": "cloud_data/rag/cloud_world_knowledge.json",
    },
}
DRAFT_FILES = {
    "fridge": "fridge_data/scenario/fridge_scene_cards_draft.json",
    "cloud": "cloud_data/scenario/cloud_scene_cards_draft.json",
}


class StoryDataError(RuntimeError):
    """데이터 파일이 없거나 형식이 맞지 않음."""


@dataclass(frozen=True, slots=True)
class OfficialData:
    project: str
    files: dict[str, dict[str, Any]]
    versions: dict[str, str]

    def get(self, name: str) -> dict[str, Any]:
        return self.files[name]


def data_root() -> Path:
    configured = os.getenv("STORY_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else _REPO_DATA


def _read(rel: str) -> dict[str, Any]:
    path = data_root() / rel
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StoryDataError(f"데이터 파일 없음: {rel}") from exc
    except json.JSONDecodeError as exc:
        raise StoryDataError(f"JSON 형식 오류: {rel}: {exc}") from exc
    if not isinstance(value, dict):
        raise StoryDataError(f"JSON 루트가 객체가 아님: {rel}")
    return value


def _check_official(project: str, files: dict[str, dict[str, Any]]) -> None:
    """프롬프트 조립에 쓰는 필드만 최소 검증한다. 값을 채우거나 바꾸지 않는다."""
    if any(f.get("project_id") != project for f in files.values()):
        raise StoryDataError(f"project_id 불일치: {project}")
    if project == "fridge":
        persona = files["persona"]
        for key in ("display_name", "speech", "forbidden", "traits"):
            if key not in persona:
                raise StoryDataError(f"냉장고 페르소나 필드 없음: {key}")
        if not isinstance(files["world"].get("restricted_topics"), list):
            raise StoryDataError("냉장고 세계관 restricted_topics 없음")
        if not isinstance(files["trailer"].get("relationship_variants"), list):
            raise StoryDataError("냉장고 예고편 relationship_variants 없음")
    else:
        names = {p.get("name") for p in files["personas"].get("personas", [])}
        if names != {"토토", "비비", "나나", "키키", "두두"}:
            raise StoryDataError("구름섬 대원 5명 정의가 아님")
        if not isinstance(files["world"].get("excluded_answer_topics"), list):
            raise StoryDataError("구름섬 세계관 excluded_answer_topics 없음")


@lru_cache(maxsize=8)
def load_official(project: str) -> OfficialData | None:
    """공식 데이터. 데이터 경로가 없으면 None (경고 로그)."""
    if project not in OFFICIAL_FILES:
        raise StoryDataError(f"알 수 없는 작품: {project}")
    try:
        files = {name: _read(rel) for name, rel in OFFICIAL_FILES[project].items()}
        _check_official(project, files)
    except StoryDataError as exc:
        logger.warning("공식 스토리 데이터 사용 불가(project=%s): %s", project, exc)
        return None
    versions = {name: str(f.get("schema_version", "?")) for name, f in files.items()}
    return OfficialData(project=project, files=files, versions=versions)


@lru_cache(maxsize=8)
def load_draft(project: str) -> dict[str, Any] | None:
    """시나리오 장면 카드 초안. 없으면 None."""
    try:
        draft = _read(DRAFT_FILES[project])
    except StoryDataError as exc:
        logger.warning("시나리오 초안 사용 불가(project=%s): %s", project, exc)
        return None
    slots = draft.get("turn_slots")
    if draft.get("project_id") != project or not isinstance(slots, list) or len(slots) != 10:
        logger.warning("시나리오 초안 형식 불일치(project=%s)", project)
        return None
    return draft


def clear_cache() -> None:
    load_official.cache_clear()
    load_draft.cache_clear()
