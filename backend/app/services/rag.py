"""RAG: 임베딩 생성 / 색인 / 검색.

PostgreSQL + pgvector 환경에서는 DB의 cosine distance 연산을 사용하고,
SQLite 개발 환경에서는 파이썬에서 코사인 유사도를 계산한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import PersonaKnowledge
from app.services.llm import get_llm
from app.services.llm.base import fit_embedding

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetrievedChunk:
    title: str
    content: str
    category: str
    score: float

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "category": self.category,
            "score": round(self.score, 4),
        }


async def index_documents(
    db: AsyncSession,
    persona_id: str,
    documents: list[dict],
    *,
    replace: bool = False,
) -> int:
    """문서 목록을 임베딩하여 저장한다. title 기준으로 upsert."""
    if not documents:
        return 0

    existing_rows = (
        await db.execute(
            select(PersonaKnowledge).where(PersonaKnowledge.persona_id == persona_id)
        )
    ).scalars().all()
    existing = {row.title: row for row in existing_rows}

    if replace:
        for row in existing_rows:
            await db.delete(row)
        existing = {}

    llm = get_llm()
    vectors = await llm.embed([doc["content"] for doc in documents])

    for document, vector in zip(documents, vectors, strict=False):
        title = document["title"]
        fitted = fit_embedding(vector, settings.embedding_dim)
        row = existing.get(title)
        if row is None:
            row = PersonaKnowledge(
                persona_id=persona_id,
                title=title,
                content=document["content"],
                category=document.get("category", "world"),
                embedding=fitted,
            )
            db.add(row)
        else:
            row.content = document["content"]
            row.category = document.get("category", row.category)
            row.embedding = fitted
    await db.flush()
    logger.info("RAG 색인 완료: persona=%s docs=%d", persona_id, len(documents))
    return len(documents)


async def retrieve(
    db: AsyncSession,
    persona_id: str,
    query: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    top_k = top_k or settings.rag_top_k
    min_score = settings.rag_min_score if min_score is None else min_score
    if not query.strip():
        return []

    llm = get_llm()
    query_vector = fit_embedding((await llm.embed([query]))[0], settings.embedding_dim)

    if settings.is_postgres:
        distance = PersonaKnowledge.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(PersonaKnowledge, distance)
            .where(
                PersonaKnowledge.persona_id == persona_id,
                PersonaKnowledge.embedding.isnot(None),
            )
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await db.execute(stmt)).all()
        chunks = [
            RetrievedChunk(
                title=row.title,
                content=row.content,
                category=row.category,
                score=1.0 - float(dist),
            )
            for row, dist in rows
        ]
    else:
        rows = (
            await db.execute(
                select(PersonaKnowledge).where(
                    PersonaKnowledge.persona_id == persona_id,
                    PersonaKnowledge.embedding.isnot(None),
                )
            )
        ).scalars().all()
        scored: list[tuple[float, PersonaKnowledge]] = []
        for row in rows:
            vector = row.embedding or []
            score = sum(a * b for a, b in zip(query_vector, vector, strict=False))
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        chunks = [
            RetrievedChunk(
                title=row.title,
                content=row.content,
                category=row.category,
                score=float(score),
            )
            for score, row in scored[:top_k]
        ]

    return [chunk for chunk in chunks if chunk.score >= min_score]
