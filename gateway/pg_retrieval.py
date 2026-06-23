"""PostgreSQL/pgvector retrieval for canon_rag (方案 B)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import psycopg

logger = logging.getLogger(__name__)


def pg_configured() -> bool:
    return bool(os.environ.get("VAJRA_CANON_PG_DSN", "").strip())


def pg_dsn() -> str:
    return os.environ.get(
        "VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon"
    )


def _hybrid_sync(
    *,
    pq: Any,
    plan: Any,
    embedding: list[float],
    series: str,
) -> tuple[list[dict[str, Any]], str | None, list[str] | None]:
    try:
        from canon.query.cache import lookup_cache
        from canon.query.pipeline import retrieve_with_plan
        from canon.query.retrieval import snippets_to_gateway_format

        series_hint = pq.series_hint or series
        with psycopg.connect(pg_dsn()) as conn:
            cached = lookup_cache(
                conn, pq.original, embedding, canon_prefixes=pq.canon_prefixes or None
            )
            if cached and cached.get("answer"):
                chunks = cached.get("top_chunks") or []
                if isinstance(chunks, list) and chunks:
                    return chunks, "cache_hit", None

            hits, sub_terms = retrieve_with_plan(conn, pq, plan, embedding)
            if plan.query_type == "D":
                logger.info(
                    "canon_rag D-class retrieve k=%s/%s sub_terms=%s boost=%s",
                    plan.vec_top,
                    plan.rerank_top,
                    sub_terms,
                    plan.doctrine_boost_prefixes,
                )
        return snippets_to_gateway_format(hits), None, sub_terms
    except Exception as exc:
        logger.warning("PG hybrid search failed: %s", exc)
        return [], str(exc), None


async def pg_query_snippets(
    *,
    pq: Any,
    plan: Any,
    embedding: list[float],
    series: str = "T",
) -> tuple[list[dict[str, Any]], str | None, list[str] | None]:
    return await asyncio.to_thread(
        _hybrid_sync,
        pq=pq,
        plan=plan,
        embedding=embedding,
        series=series,
    )


def store_answer_cache(
    *,
    pq: Any,
    embedding: list[float],
    snippets: list[dict[str, Any]],
    answer: str,
) -> None:
    try:
        from canon.query.cache import store_cache

        with psycopg.connect(pg_dsn()) as conn:
            store_cache(conn, pq.original, embedding, snippets, answer)
    except Exception as exc:
        logger.warning("cache store failed: %s", exc)
