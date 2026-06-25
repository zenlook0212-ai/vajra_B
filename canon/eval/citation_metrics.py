"""Citation quality metrics for gateway synthesis eval (Phase 2A)."""

from __future__ import annotations

import re
from typing import Any

import psycopg

_COORD_CITE_RE = re.compile(r"【([A-Z]{1,3}\d+n\d+_[^】]+)】", re.I)
_CANON_ID_RE = re.compile(r"\b([A-Z]{1,3}\d+n\d+[a-zA-Z]?)\b", re.I)


def extract_citations(text: str) -> list[str]:
    return [m.group(1) for m in _COORD_CITE_RE.finditer(text or "")]


def extract_canon_ids(text: str) -> list[str]:
    return [m.group(1).upper() for m in _CANON_ID_RE.finditer(text or "")]


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


def score_answer_citations(
    conn: psycopg.Connection,
    *,
    answer: str,
    snippets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score one synthesized answer against retrieval context."""
    cites = extract_citations(answer)
    retrieved_ids = snippet_chunk_ids(snippets)
    retrieved_canons = snippet_canon_ids(snippets)

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
        in_ret = chunk_id is not None and chunk_id in retrieved_ids
        retrieval_flags.append(in_ret)
        if not in_ret:
            not_from_retrieval.append(coord)

    canon_in_answer = extract_canon_ids(answer)
    stray_canons = [
        c for c in canon_in_answer if not any(c.startswith(rc) or rc.startswith(c) for rc in retrieved_canons)
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
