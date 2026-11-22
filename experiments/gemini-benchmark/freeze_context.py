"""기준 커밋의 작품 설정과 장면 지시를 독립 실험 입력으로 내보냅니다."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["STORY_DATA_DIR"] = str(ROOT / "data")

from app.services.story_scenes import fill_user, get_project
from app.services.story_prompt import character_rules, scene_card
from app.services.story_scene_sets import format_line


def main():
    context = {}
    for key in ("fridge", "cloud"):
        project = get_project(key, "scenario_draft_v1")
        context[key] = {
            "rules": character_rules(project, "솔빛")[0],
            "scenes": [scene_card(project, i, scene, "솔빛") for i, scene in enumerate(project.scenes)],
            "fixed": "\n".join(fill_user(line.speaker + ": " + format_line(line, key), "솔빛")
                               for line in project.scenes[-1].fixed_lines),
        }
    draft = (ROOT / "prompts/pruma_system.md").read_text()
    context["puruma"] = {
        "rules": draft[draft.index("## 1."):draft.index("## 8.")].strip(),
        "scenes": [
            "개강 1턴. 지도를 보고 강의실 앞에 도착하니 수업이 이미 시작됐다. 어떻게 들어갈지 묻는다.",
            "개강 2턴. 뒷문으로 들어가다 말발굽 소리를 낸다.",
            "적응. 학식 추천 받기", "적응. 관심 있는 동아리 이야기",
            "중간고사. 공부 장소 고민", "중간고사. 복습 방법 이야기",
            "축제. 공연 기다리기", "축제. 푸드트럭 구경", "축제. 함께 보낸 하루",
            "기말·종강. 성적 걱정과 응원",
        ],
    }
    (HERE / "prompt_context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
