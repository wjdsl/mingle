"""호칭 자리표시 {{user}} 통일 테스트 (외부 API 없음, 2026-11-22).

- 데이터·문서·대체 규칙의 호칭 자리는 {{user}} 하나로 쓴다.
- 실행 시 사용자 호칭, 쓸 수 없으면 작품별 기본 호칭으로 바뀐다.
- 옛 표기 [호칭]/[닉네임]/{nickname}도 당분간 같이 바뀐다.
- 프롬프트 템플릿의 설정값 자리({{title}}, {{user_title}} 등)와 섞이지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.story_prompt import build_story_messages
from app.services.story_scenes import LEGACY_USER_TOKENS, USER_TOKEN, fill_user, get_project
from app.services.story_turn_service import safe_nickname

SCENARIO = "scenario_draft_v1"
ROOT = Path(__file__).resolve().parents[2]
ANY_TOKEN = re.compile(r"\{\{user\}\}|\[(호칭|닉네임)\]|\{nickname\}")
DATA_FILES = [
    "data/cloud_data/scenario/cloud_scene_cards_draft.json",
    "data/fridge_data/scenario/fridge_scene_cards_draft.json",
    "data/fridge_data/scenario/fridge_trailer_cuts.json",
    "data/cloud_data/persona/cloud_personas.json",
    "data/fridge_data/rules/fridge_relationship_rules.json",
]


def test_fill_user_replaces_new_and_legacy_tokens():
    text = f"{USER_TOKEN} / " + " / ".join(LEGACY_USER_TOKENS)
    assert fill_user(text, "하늘") == " / ".join(["하늘"] * (1 + len(LEGACY_USER_TOKENS)))


def test_fill_user_does_not_touch_template_keys():
    # {{user}}와 접두가 같은 설정값 자리는 그대로 둔다(템플릿은 _fill이 따로 채운다).
    assert fill_user("{{user_title}} {{users}} {{title}}", "하늘") == "{{user_title}} {{users}} {{title}}"


def test_data_files_use_only_new_token():
    for rel in DATA_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert USER_TOKEN in text, rel
        assert not any(token in text for token in LEGACY_USER_TOKENS), rel


@pytest.mark.parametrize("project_id", ["fridge", "cloud"])
def test_prompt_has_no_unfilled_token_and_uses_nickname(project_id):
    project = get_project(project_id, SCENARIO)
    for turn, scene in enumerate(project.scenes):
        if scene.input_mode == "none":
            continue
        messages, _ = build_story_messages(project, "하늘", turn, [], "안녕", None)
        system = messages[0]["content"]
        assert not ANY_TOKEN.search(system), (project_id, turn)
        assert "{{" not in system, (project_id, turn)  # 템플릿 설정값도 모두 채워진다


def test_cloud_turn1_example_uses_real_nickname():
    project = get_project("cloud", SCENARIO)
    messages, _ = build_story_messages(project, "하늘", 0, [], "저 좀 떨려요", None)
    assert '나나가 "하늘, 처음이라 떨리지? 괜찮아."' in messages[0]["content"]


@pytest.mark.parametrize("raw", ["", "   ", "{{user}}", "[민트]", "010-1234-5678"])
def test_unusable_nickname_falls_back_to_project_default(raw):
    for project_id in ("fridge", "cloud"):
        fallback = get_project(project_id, SCENARIO).nickname_fallback
        assert safe_nickname(raw, fallback) == fallback
        assert fill_user(f"{USER_TOKEN}, 반가워.", safe_nickname(raw, fallback)) == f"{fallback}, 반가워."


def test_cloud_persona_address_reaches_prompt():
    personas = json.loads((ROOT / "data/cloud_data/persona/cloud_personas.json").read_text(encoding="utf-8"))
    assert USER_TOKEN in json.dumps(personas, ensure_ascii=False)
    project = get_project("cloud", SCENARIO)
    system = build_story_messages(project, "하늘", 1, [], "안녕", None)[0][0]["content"]
    assert "하늘 대원!" in system  # 토토 호칭 "{{user}} 대원!"
