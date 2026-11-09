"""페르소나 지식 문서를 JSON 파일에서 읽어 RAG 색인에 추가한다.

사용 예:
    python -m scripts.ingest --persona seo-harin --file docs.json

docs.json 형식:
    [
      {"title": "세계관 · 아르덴 제국", "content": "...", "category": "world"},
      {"title": "메뉴 · 시그니처", "content": "...", "category": "product"}
    ]

category: world | character | product | faq
같은 title이 이미 있으면 내용을 갱신하고 재임베딩한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.base import SessionLocal, init_db  # noqa: E402
from app.db.models import Persona  # noqa: E402
from app.services.rag import index_documents  # noqa: E402


async def run(persona_slug: str, file_path: Path) -> int:
    documents = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(documents, list):
        raise SystemExit("JSON 최상위는 배열이어야 합니다.")

    await init_db()
    async with SessionLocal() as db:
        persona = (
            await db.execute(select(Persona).where(Persona.slug == persona_slug))
        ).scalar_one_or_none()
        if persona is None:
            raise SystemExit(f"페르소나를 찾을 수 없습니다: {persona_slug}")

        count = await index_documents(db, persona.id, documents, replace=False)
        await db.commit()
        print(f"{persona.name}({persona.slug}) 지식 {count}건 색인 완료")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="페르소나 RAG 지식 문서 색인")
    parser.add_argument("--persona", required=True, help="페르소나 slug")
    parser.add_argument("--file", required=True, type=Path, help="JSON 파일 경로")
    args = parser.parse_args()
    asyncio.run(run(args.persona, args.file))


if __name__ == "__main__":
    main()
