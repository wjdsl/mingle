"""모든(또는 특정) 페르소나의 RAG 지식을 다시 임베딩한다.

LLM 공급자를 바꾸었거나, 임베딩 요청이 일시적으로 실패한 경우 사용한다.

사용 예:
    python -m scripts.reindex
    python -m scripts.reindex --persona seo-harin
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.base import SessionLocal, init_db  # noqa: E402
from app.db.models import Persona, PersonaKnowledge  # noqa: E402
from app.services.llm import LLMError, get_llm  # noqa: E402
from app.services.rag import index_documents  # noqa: E402


async def run(persona_slug: str | None) -> None:
    await init_db()
    print(f"임베딩 공급자: {get_llm().name}")

    async with SessionLocal() as db:
        stmt = select(Persona).order_by(Persona.sort_order)
        if persona_slug:
            stmt = stmt.where(Persona.slug == persona_slug)
        personas = (await db.execute(stmt)).scalars().all()
        if not personas:
            raise SystemExit("대상 페르소나가 없습니다.")

        total = 0
        for persona in personas:
            rows = (
                await db.execute(
                    select(PersonaKnowledge).where(
                        PersonaKnowledge.persona_id == persona.id
                    )
                )
            ).scalars().all()
            documents = [
                {"title": row.title, "content": row.content, "category": row.category}
                for row in rows
            ]
            if not documents:
                print(f"- {persona.name}: 지식 없음 (건너뜀)")
                continue
            try:
                await index_documents(db, persona.id, documents)
                await db.commit()
                total += len(documents)
                print(f"- {persona.name}: {len(documents)}건 재임베딩 완료")
            except LLMError as exc:
                await db.rollback()
                print(f"- {persona.name}: 실패 ({exc})")

        print(f"총 {total}건 완료")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 지식 재임베딩")
    parser.add_argument("--persona", default=None, help="특정 페르소나 slug (생략 시 전체)")
    args = parser.parse_args()
    asyncio.run(run(args.persona))


if __name__ == "__main__":
    main()
