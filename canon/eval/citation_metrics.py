"""Citation quality metrics for gateway synthesis eval (Phase 2A)."""

from __future__ import annotations

import re
from typing import Any

import psycopg

_COORD_CITE_RE = re.compile(r"【([A-Z]{1,3}\d+n\d+_[^】]+)】", re.I)
_COORD_CITE_BLOCK_RE = re.compile(
    r"【[A-Z]{1,3}\d+n\d+_[^】]+】(?:\([^)]+\))?",
    re.I,
)
_ASPECT_HEADER_RE = re.compile(r"【[^】]*／[^】]*】")
_CANON_ID_RE = re.compile(r"\b([A-Z]{1,3}\d+n\d+[a-zA-Z]?)\b", re.I)
_CONSERVATIVE_REFUSAL_RE = re.compile(
    r"現有語料不足以確認|語料不足|無法從現有語料"
)


def extract_citations(text: str) -> list[str]:
    return [m.group(1) for m in _COORD_CITE_RE.finditer(text or "")]


def strip_citation_blocks(text: str) -> str:
    """Remove coord cites (and optional parenthetical canon) and aspect headers."""
    t = text or ""
    t = _COORD_CITE_BLOCK_RE.sub("", t)
    t = _ASPECT_HEADER_RE.sub("", t)
    return t


def extract_canon_ids(text: str) -> list[str]:
    return [m.group(1).upper() for m in _CANON_ID_RE.finditer(text or "")]


def is_conservative_refusal(answer: str) -> bool:
    return bool(_CONSERVATIVE_REFUSAL_RE.search(answer or ""))


def _canon_from_coord(coord: str) -> str | None:
    m = re.search(r"([A-Z]{1,3}\d+n\d+)", coord, re.I)
    return m.group(1).upper() if m else None


def normalize_citation_coord(coord: str) -> str:
    """Normalize cite to DB point key (with trailing _)."""
    c = coord.strip().strip("【】").rstrip("_")
    return f"{c}_"


def citation_exists(conn: psycopg.Connection, coord: str) -> bool:
    cite = normalize_citation_coord(coord)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM canon_chunks
            WHERE coord_start <= %s AND coord_end >= %s
            LIMIT 1
            """,
            (cite, cite),
        )
        return cur.fetchone() is not None


def chunk_id_for_citation(conn: psycopg.Connection, coord: str) -> int | None:
    cite = normalize_citation_coord(coord)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM canon_chunks
            WHERE coord_start <= %s AND coord_end >= %s
            LIMIT 1
            """,
            (cite, cite),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def snippet_chunk_ids(snippets: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for sn in snippets:
        sid = sn.get("id")
        if isinstance(sid, int):
            out.add(sid)
    return out


def snippet_canon_ids(snippets: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for sn in snippets:
        cid = sn.get("canon_id")
        if cid:
            out.add(str(cid).upper())
        meta = sn.get("metadata") or {}
        if meta.get("canon_id"):
            out.add(str(meta["canon_id"]).upper())
    return out


def citation_from_retrieval(
    *,
    chunk_id: int | None,
    coord: str,
    retrieved_ids: set[int],
    retrieved_canons: set[str],
) -> bool:
    """True if citation is traceable to the retrieval pool."""
    if chunk_id is not None and chunk_id in retrieved_ids:
        return True
    coord_canon = _canon_from_coord(coord)
    if not coord_canon:
        return False
    if coord_canon in retrieved_canons:
        return True
    for rc in retrieved_canons:
        if coord_canon.startswith(rc) or rc.startswith(coord_canon):
            return True
    return False


def score_answer_citations(
    conn: psycopg.Connection,
    *,
    answer: str,
    snippets: list[dict[str, Any]],
    trace_snippets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score one synthesized answer against retrieval context."""
    cites = extract_citations(answer)
    pool = trace_snippets if trace_snippets is not None else snippets
    retrieved_ids = snippet_chunk_ids(pool)
    retrieved_canons = snippet_canon_ids(pool)

    valid_flags: list[bool] = []
    retrieval_flags: list[bool] = []
    invalid_coords: list[str] = []
    not_from_retrieval: list[str] = []

    for coord in cites:
        ok = citation_exists(conn, coord)
        valid_flags.append(ok)
        if not ok:
            invalid_coords.append(coord)
            retrieval_flags.append(False)
            continue
        chunk_id = chunk_id_for_citation(conn, coord)
        in_ret = citation_from_retrieval(
            chunk_id=chunk_id,
            coord=coord,
            retrieved_ids=retrieved_ids,
            retrieved_canons=retrieved_canons,
        )
        retrieval_flags.append(in_ret)
        if not in_ret:
            not_from_retrieval.append(coord)

    canon_in_answer = extract_canon_ids(strip_citation_blocks(answer))
    stray_canons = [
        c
        for c in canon_in_answer
        if not any(c.startswith(rc) or rc.startswith(c) for rc in retrieved_canons)
    ]

    n = len(cites)
    return {
        "n_citations": n,
        "citation_valid_rate": (sum(valid_flags) / n) if n else None,
        "citation_from_retrieval_rate": (sum(retrieval_flags) / n) if n else None,
        "has_citation": n > 0,
        "all_citations_valid": n > 0 and all(valid_flags),
        "all_citations_from_retrieval": n > 0 and all(retrieval_flags),
        "invalid_coords": invalid_coords,
        "not_from_retrieval": not_from_retrieval,
        "stray_canon_ids": stray_canons,
        "has_stray_canon_id": bool(stray_canons),
    }
