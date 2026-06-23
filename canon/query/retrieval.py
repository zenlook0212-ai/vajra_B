"""Hybrid retrieval: vector + BM25 + RRF + optional rerank."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
import psycopg

RRF_K = 60
VEC_TOP = 20
BM25_TOP = 20
FUSE_TOP = 30
FINAL_TOP = 5
CANON_FILTER_MIN_HITS = 1
VEC_OVERFETCH = 200  # used when app-side canon filter after HNSW
HNSW_EF_SEARCH = 400

_CANON_ID_RE = re.compile(r"\b([A-Z]{1,3}\d+n\d+[a-zA-Z]?)\b", re.I)


def pg_dsn() -> str:
    return os.environ.get(
        "VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon"
    )


def _series_key(series: str) -> str:
    s = series.strip().upper()
    return s if len(s) <= 2 else s[:2]


def _canon_filter_sql(canon_prefixes: list[str] | None) -> tuple[str, list[str]]:
    if not canon_prefixes:
        return "", []
    patterns = [f"{p}%" for p in canon_prefixes]
    clause = " AND (" + " OR ".join("canon_id ILIKE %s" for _ in patterns) + ")"
    return clause, patterns


def _canon_id_match(query: str, canon_id: str) -> bool:
    q_ids = {m.group(1).upper() for m in _CANON_ID_RE.finditer(query)}
    return canon_id.upper() in q_ids if q_ids else False


def rrf_score(rank: int, k: int = RRF_K) -> float:
    return 1.0 / (k + rank)


def _matches_doctrine_prefixes(canon_id: str, prefixes: list[str]) -> bool:
    cid = canon_id.upper()
    for p in prefixes:
        if cid.startswith(p.upper()):
            return True
    return False


def _volume_from_canon(canon_id: str) -> int | None:
    cid = canon_id.upper()
    if not cid.startswith("T") or len(cid) < 3:
        return None
    vol = cid[1:3]
    return int(vol) if vol.isdigit() else None


def _rrf_doctrine_multiplier(
    canon_id: str,
    doctrine_boost_prefixes: list[str] | None,
) -> float:
    """Tiered boost for expected sutra families; demote non-target corpora on D-class."""
    if not doctrine_boost_prefixes:
        return 1.0
    cid = canon_id.upper()
    for i, p in enumerate(doctrine_boost_prefixes):
        if cid.startswith(p.upper()):
            if i == 0:
                return 2.0
            if i == 1:
                return 1.75
            return 1.55
    return 0.18


def rrf_fuse(
    vec_ranks: dict[int, int],
    bm25_ranks: dict[int, int],
    *,
    query: str,
    chunk_canon: dict[int, str],
    extra_rank_lists: list[dict[int, int]] | None = None,
    k: int = RRF_K,
    canon_bonus: float = 1.5,
    doctrine_bonus: float = 1.45,
    doctrine_boost_prefixes: list[str] | None = None,
    limit: int = FUSE_TOP,
) -> list[tuple[int, float]]:
    ids = set(vec_ranks) | set(bm25_ranks)
    if extra_rank_lists:
        for rl in extra_rank_lists:
            ids |= set(rl)
    scores: dict[int, float] = {}
    for cid in ids:
        s = rrf_score(vec_ranks.get(cid, k + 1), k) + rrf_score(bm25_ranks.get(cid, k + 1), k)
        if extra_rank_lists:
            for rl in extra_rank_lists:
                s += rrf_score(rl.get(cid, k + 1), k)
        chunk_id = chunk_canon.get(cid, "")
        if _canon_id_match(query, chunk_id):
            s *= canon_bonus
        elif doctrine_boost_prefixes:
            s *= _rrf_doctrine_multiplier(chunk_id, doctrine_boost_prefixes)
        scores[cid] = s
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:limit]


def _matches_canon_prefixes(canon_id: str, prefixes: list[str]) -> bool:
    cid = canon_id.upper()
    for p in prefixes:
        if cid.startswith(p.upper()):
            return True
    return False


def vector_search(
    conn: psycopg.Connection,
    embedding: list[float],
    *,
    series: str = "T",
    limit: int = VEC_TOP,
    canon_prefixes: list[str] | None = None,
) -> list[dict[str, Any]]:
    key = _series_key(series)
    emb_lit = "[" + ",".join(str(float(x)) for x in embedding) + "]"
    # pgvector HNSW + extra WHERE on canon_id can return empty; over-fetch then filter.
    sql_limit = limit
    canon_clause = ""
    canon_params: list[str] = []
    if canon_prefixes:
        sql_limit = VEC_OVERFETCH
    else:
        canon_clause, canon_params = _canon_filter_sql(canon_prefixes)
    with conn.cursor() as cur:
        cur.execute(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}")
        cur.execute(
            f"""
            SELECT id, canon_id, coord_start, coord_end, text, char_len,
                   embedding <=> %s::halfvec AS distance
            FROM canon_chunks
            WHERE series = %s AND embedding IS NOT NULL{canon_clause}
            ORDER BY embedding <=> %s::halfvec
            LIMIT %s
            """,
            (emb_lit, key, *canon_params, emb_lit, sql_limit),
        )
        rows = cur.fetchall()
    hits = [
        {
            "id": r[0],
            "canon_id": r[1],
            "coord_start": r[2],
            "coord_end": r[3],
            "text": r[4],
            "char_len": r[5],
            "distance": float(r[6]),
            "metadata": {
                "canon_id": r[1],
                "coord_start": r[2],
                "coord_end": r[3],
            },
        }
        for r in rows
    ]
    if canon_prefixes:
        hits = [h for h in hits if _matches_canon_prefixes(h["canon_id"], canon_prefixes)]
        hits = hits[:limit]
    return hits


def bm25_search(
    conn: psycopg.Connection,
    query: str,
    *,
    series: str = "T",
    limit: int = BM25_TOP,
    canon_prefixes: list[str] | None = None,
) -> list[dict[str, Any]]:
    key = _series_key(series)
    canon_clause, canon_params = _canon_filter_sql(canon_prefixes)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, canon_id, coord_start, coord_end, text, char_len,
                   ts_rank(tsv, plainto_tsquery('simple', %s)) AS rank
            FROM canon_chunks
            WHERE series = %s AND tsv @@ plainto_tsquery('simple', %s){canon_clause}
            ORDER BY rank DESC
            LIMIT %s
            """,
            (query, key, query, *canon_params, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "canon_id": r[1],
            "coord_start": r[2],
            "coord_end": r[3],
            "text": r[4],
            "char_len": r[5],
            "rank": float(r[6]),
            "metadata": {
                "canon_id": r[1],
                "coord_start": r[2],
                "coord_end": r[3],
            },
        }
        for r in rows
    ]


def keyword_search(
    conn: psycopg.Connection,
    term: str,
    *,
    series: str = "T",
    limit: int = 10,
    canon_prefixes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Chinese substring match (pg_trgm-backed when index present)."""
    key = _series_key(series)
    canon_clause, canon_params = _canon_filter_sql(canon_prefixes)
    pattern = f"%{term}%"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, canon_id, coord_start, coord_end, text, char_len,
                   1.0 AS rank
            FROM canon_chunks
            WHERE series = %s AND text LIKE %s{canon_clause}
            LIMIT %s
            """,
            (key, pattern, *canon_params, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "canon_id": r[1],
            "coord_start": r[2],
            "coord_end": r[3],
            "text": r[4],
            "char_len": r[5],
            "rank": float(r[6]),
            "metadata": {
                "canon_id": r[1],
                "coord_start": r[2],
                "coord_end": r[3],
            },
        }
        for r in rows
    ]


def hybrid_search(
    conn: psycopg.Connection,
    *,
    bm25_query: str,
    embedding: list[float],
    rerank_query: str | None = None,
    series: str = "T",
    canon_prefixes: list[str] | None = None,
    sub_terms: list[str] | None = None,
    vec_top: int = VEC_TOP,
    bm25_top: int = BM25_TOP,
    fuse_top: int = FUSE_TOP,
    rerank_top: int = FINAL_TOP,
    sub_term_bm25_top: int = 10,
    doctrine_boost_prefixes: list[str] | None = None,
    use_rrf: bool = True,
    rerank: bool = True,
) -> list[dict[str, Any]]:
    rerank_q = rerank_query or bm25_query
    prefixes = canon_prefixes or None
    vec_hits = vector_search(
        conn, embedding, series=series, limit=vec_top, canon_prefixes=prefixes
    )
    bm25_hits = bm25_search(
        conn, bm25_query, series=series, limit=bm25_top, canon_prefixes=prefixes
    )

    sub_rank_lists: list[dict[int, int]] = []
    sub_hits: list[dict[str, Any]] = []
    kw_prefixes = prefixes
    if not kw_prefixes and doctrine_boost_prefixes:
        kw_prefixes = doctrine_boost_prefixes
    if sub_terms:
        for term in sub_terms:
            hits = keyword_search(
                conn,
                term,
                series=series,
                limit=sub_term_bm25_top,
                canon_prefixes=kw_prefixes,
            )
            sub_hits.extend(hits)
            sub_rank_lists.append({h["id"]: i + 1 for i, h in enumerate(hits)})

    all_hits = vec_hits + bm25_hits + sub_hits
    if prefixes and len({h["id"] for h in all_hits}) < CANON_FILTER_MIN_HITS:
        vec_hits = vector_search(conn, embedding, series=series, limit=vec_top)
        bm25_hits = bm25_search(conn, bm25_query, series=series, limit=bm25_top)
        sub_rank_lists = []
        sub_hits = []
        if sub_terms:
            for term in sub_terms:
                hits = keyword_search(
                    conn, term, series=series, limit=sub_term_bm25_top, canon_prefixes=kw_prefixes
                )
                sub_hits.extend(hits)
                sub_rank_lists.append({h["id"]: i + 1 for i, h in enumerate(hits)})
        all_hits = vec_hits + bm25_hits + sub_hits

    if not use_rrf:
        merged = {h["id"]: h for h in all_hits}
        return list(merged.values())[:rerank_top]

    vec_ranks = {h["id"]: i + 1 for i, h in enumerate(vec_hits)}
    bm25_ranks = {h["id"]: i + 1 for i, h in enumerate(bm25_hits)}
    by_id: dict[int, dict[str, Any]] = {}
    chunk_canon: dict[int, str] = {}
    for h in all_hits:
        by_id[h["id"]] = h
        chunk_canon[h["id"]] = h.get("canon_id", "")

    fused = rrf_fuse(
        vec_ranks,
        bm25_ranks,
        query=bm25_query,
        chunk_canon=chunk_canon,
        extra_rank_lists=sub_rank_lists or None,
        doctrine_boost_prefixes=doctrine_boost_prefixes,
        limit=fuse_top,
    )
    snippets = [by_id[cid] for cid, _ in fused if cid in by_id]

    if rerank and snippets:
        from canon.query.rerank import rerank_snippets

        snippets = rerank_snippets(rerank_q, snippets, top_k=rerank_top)
    else:
        snippets = snippets[:rerank_top]

    return snippets


def snippets_to_gateway_format(snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape for gateway rag_retrieval compatibility."""
    out: list[dict[str, Any]] = []
    for sn in snippets:
        out.append(
            {
                "text": sn.get("text", ""),
                "distance": sn.get("distance"),
                "metadata": sn.get("metadata") or {},
            }
        )
    return out


async def async_hybrid_search(
    *,
    query: str,
    embedding: list[float],
    series: str = "T",
) -> list[dict[str, Any]]:
    """Sync PG work in thread pool friendly wrapper for gateway."""
    with psycopg.connect(pg_dsn()) as conn:
        hits = hybrid_search(
            conn, bm25_query=query, embedding=embedding, series=series
        )
    return snippets_to_gateway_format(hits)
