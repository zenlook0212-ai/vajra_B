"""Semantic query cache (PG-backed)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

CACHE_TTL_DAYS = int(os.environ.get("VAJRA_CANON_CACHE_TTL_DAYS", "7"))
CACHE_THRESHOLD = float(os.environ.get("VAJRA_CANON_CACHE_COSINE", "0.95"))


CACHE_KEY_VERSION = os.environ.get("VAJRA_CANON_CACHE_KEY_VERSION", "phase_a6_v2")
MIN_CACHE_CHUNKS = int(os.environ.get("VAJRA_CANON_CACHE_MIN_CHUNKS", "3"))


def pg_dsn() -> str:
    return os.environ.get(
        "VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon"
    )


def _query_hash(query: str) -> str:
    payload = f"{CACHE_KEY_VERSION}:{query.strip()}"
    return hashlib.sha256(payload.encode()).hexdigest()


def lookup_cache(
    conn: psycopg.Connection,
    query: str,
    query_embed: list[float],
) -> dict[str, Any] | None:
    qh = _query_hash(query)
    emb_lit = "[" + ",".join(str(float(x)) for x in query_embed) + "]"
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT query_hash, top_chunks, answer,
                   1 - (query_embed <=> %s::halfvec) AS cosine
            FROM semantic_cache
            WHERE created_at >= %s AND query_hash = %s
            LIMIT 1
            """,
            (emb_lit, cutoff, qh),
        )
        row = cur.fetchone()
    if not row:
        return None
    cosine = float(row[3]) if row[3] is not None else 0.0
    if cosine < CACHE_THRESHOLD:
        return None
    top_chunks = row[1]
    if not isinstance(top_chunks, list) or len(top_chunks) < MIN_CACHE_CHUNKS:
        return None
    return {
        "query_hash": row[0],
        "top_chunks": top_chunks,
        "answer": row[2],
        "cosine": cosine,
    }


def store_cache(
    conn: psycopg.Connection,
    query: str,
    query_embed: list[float],
    top_chunks: list[dict[str, Any]],
    answer: str,
) -> None:
    qh = _query_hash(query)
    emb_lit = "[" + ",".join(str(float(x)) for x in query_embed) + "]"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO semantic_cache (query_hash, query_embed, top_chunks, answer)
            VALUES (%s, %s::halfvec, %s::jsonb, %s)
            ON CONFLICT (query_hash) DO UPDATE SET
              query_embed = EXCLUDED.query_embed,
              top_chunks = EXCLUDED.top_chunks,
              answer = EXCLUDED.answer,
              created_at = now()
            """,
            (qh, emb_lit, json.dumps(top_chunks, ensure_ascii=False), answer),
        )
    conn.commit()


def purge_expired(conn: psycopg.Connection) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM semantic_cache WHERE created_at < %s", (cutoff,))
        n = cur.rowcount
    conn.commit()
    return n
