"""Semantic query cache (PG-backed)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

CACHE_TTL_DAYS = int(os.environ.get("VAJRA_CANON_CACHE_TTL_DAYS", "7"))
CACHE_THRESHOLD = float(os.environ.get("VAJRA_CANON_CACHE_COSINE", "0.95"))

# Bump when synthesis format changes (e.g. extractive cite suffix removal).
CACHE_KEY_VERSION = os.environ.get("VAJRA_CANON_CACHE_KEY_VERSION", "phase_2c_v5")
_OLD_CITE_SUFFIX_RE = re.compile(r"】\s*\([A-Z]{1,3}\d+n\d+", re.I)
MIN_CACHE_CHUNKS = int(os.environ.get("VAJRA_CANON_CACHE_MIN_CHUNKS", "3"))


def pg_dsn() -> str:
    return os.environ.get(
        "VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon"
    )


def _query_hash(query: str) -> str:
    payload = f"{CACHE_KEY_VERSION}:{query.strip()}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _chunk_canon_id(chunk: dict[str, Any]) -> str:
    meta = chunk.get("metadata")
    if isinstance(meta, dict) and meta.get("canon_id"):
        return str(meta["canon_id"]).upper()
    if chunk.get("canon_id"):
        return str(chunk["canon_id"]).upper()
    return ""


def is_stale_cached_answer(answer: str) -> bool:
    """Reject cached answers from older synthesis formats or incomplete D-class output."""
    text = (answer or "").strip()
    if not text:
        return True
    if _OLD_CITE_SUFFIX_RE.search(text):
        return True
    if "【義理面向】" in text and "【綜合回答】" not in text:
        return True
    return False


def cache_matches_scope(
    top_chunks: list[dict[str, Any]],
    canon_prefixes: list[str] | None,
) -> bool:
    """Reject scoped-query cache hits that lack primary canon evidence."""
    if not canon_prefixes:
        return True
    prefixes = [p.upper() for p in canon_prefixes if p]
    if not prefixes:
        return True
    ids = [_chunk_canon_id(ch) for ch in top_chunks if isinstance(ch, dict)]
    ids = [cid for cid in ids if cid]
    if not ids:
        return False
    if len(prefixes) == 1:
        p = prefixes[0]
        return any(cid.startswith(p) for cid in ids[:3])
    return any(any(cid.startswith(p) for p in prefixes) for cid in ids[:3])


def lookup_cache(
    conn: psycopg.Connection,
    query: str,
    query_embed: list[float],
    *,
    canon_prefixes: list[str] | None = None,
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
    if not cache_matches_scope(top_chunks, canon_prefixes):
        return None
    answer = str(row[2] or "")
    if is_stale_cached_answer(answer):
        return None
    return {
        "query_hash": row[0],
        "top_chunks": top_chunks,
        "answer": answer,
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


def purge_stale_cache(conn: psycopg.Connection) -> int:
    """Delete cached answers that fail is_stale_cached_answer."""
    with conn.cursor() as cur:
        cur.execute("SELECT query_hash, answer FROM semantic_cache")
        rows = cur.fetchall()
    stale = [h for h, a in rows if is_stale_cached_answer(str(a or ""))]
    if not stale:
        return 0
    with conn.cursor() as cur:
        cur.execute("DELETE FROM semantic_cache WHERE query_hash = ANY(%s)", (stale,))
    conn.commit()
    return len(stale)


def purge_expired(conn: psycopg.Connection) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM semantic_cache WHERE created_at < %s", (cutoff,))
        n = cur.rowcount
    conn.commit()
    return n
