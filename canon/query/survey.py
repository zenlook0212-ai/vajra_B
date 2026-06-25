"""Corpus-wide occurrence survey (B1): list sutras mentioning a term."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any

import psycopg

from canon.query.preprocess import TERM_MAP
from canon.query.retrieval import bm25_search, keyword_search

_SURVEY_HIT_LIMIT = int(os.environ.get("VAJRA_SURVEY_HIT_LIMIT", "200"))
_SURVEY_MAX_CANONS = int(os.environ.get("VAJRA_SURVEY_MAX_CANONS", "40"))
_SURVEY_SAMPLES_PER_CANON = int(os.environ.get("VAJRA_SURVEY_SAMPLES_PER_CANON", "2"))


def _coord_display(coord_start: str) -> str:
    inner = str(coord_start or "").strip().strip("【】").rstrip("_")
    return f"【{inner}】" if inner else ""


def expand_survey_terms(query: str) -> list[str]:
    """Primary query + matched doctrine synonyms for broader recall."""
    q = (query or "").strip()
    if not q:
        return []
    terms: list[str] = [q]
    for key in sorted(TERM_MAP.keys(), key=len, reverse=True):
        if key in q:
            if key not in terms:
                terms.insert(1 if terms else 0, key)
            for alt in TERM_MAP[key]:
                if alt not in terms and len(alt) >= 2:
                    terms.append(alt)
            break
    # Short doctrine-only queries
    if q in TERM_MAP:
        for alt in TERM_MAP[q]:
            if alt not in terms:
                terms.append(alt)
    return terms[:6]


def _search_term(
    conn: psycopg.Connection,
    term: str,
    *,
    series: str,
) -> list[dict[str, Any]]:
    hits = bm25_search(conn, term, series=series, limit=_SURVEY_HIT_LIMIT)
    if len(hits) < 5 and len(term) >= 2:
        extra = keyword_search(conn, term, series=series, limit=_SURVEY_HIT_LIMIT)
        seen = {h["id"] for h in hits}
        for h in extra:
            if h["id"] not in seen:
                hits.append(h)
                seen.add(h["id"])
    return hits


def survey_occurrences(
    conn: psycopg.Connection,
    query: str,
    *,
    series: str = "T",
) -> dict[str, Any]:
    """Return grouped hits by canon_id with sample coords."""
    terms = expand_survey_terms(query)
    by_canon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_chunk: set[int] = set()

    for term in terms:
        for hit in _search_term(conn, term, series=series):
            cid = str(hit.get("canon_id") or "").upper()
            chunk_id = hit.get("id")
            if not cid or not isinstance(chunk_id, int):
                continue
            if chunk_id in seen_chunk:
                continue
            seen_chunk.add(chunk_id)
            by_canon[cid].append(hit)

    ranked = sorted(
        by_canon.items(),
        key=lambda kv: (len(kv[1]), max(h.get("rank", 0) for h in kv[1])),
        reverse=True,
    )[:_SURVEY_MAX_CANONS]

    groups: list[dict[str, Any]] = []
    for canon_id, hits in ranked:
        hits.sort(key=lambda h: float(h.get("rank") or 0), reverse=True)
        samples: list[dict[str, str]] = []
        for h in hits[:_SURVEY_SAMPLES_PER_CANON]:
            coord = _coord_display(str(h.get("coord_start") or ""))
            excerpt = re.sub(r"\s+", "", str(h.get("text") or ""))[:80]
            samples.append({"coord": coord, "excerpt": excerpt})
        groups.append(
            {
                "canon_id": canon_id,
                "hit_count": len(hits),
                "samples": samples,
            }
        )

    return {
        "query": query.strip(),
        "terms_searched": terms,
        "total_hits": len(seen_chunk),
        "canon_count": len(groups),
        "groups": groups,
    }


def format_survey_markdown(
    report: dict[str, Any],
    *,
    cbeta_url_fn: Any,
) -> str:
    """Human-readable survey for WebUI / gateway output."""
    q = report.get("query") or ""
    terms = report.get("terms_searched") or []
    groups = report.get("groups") or []
    total = report.get("total_hits", 0)
    n_canon = report.get("canon_count", 0)

    lines = [
        f"【全藏出處】「{q}」",
        f"檢索詞：{'、'.join(terms)}；語料內共 **{total}** 段、**{n_canon}** 部經（已匯入 corpus；非 CBETA 官網全庫）。",
        "",
    ]
    if not groups:
        lines.append("現有語料中未找到相關段落。")
        return "\n".join(lines)

    for i, g in enumerate(groups, start=1):
        cid = g.get("canon_id", "")
        url = cbeta_url_fn(cid) if cbeta_url_fn else None
        label = f"[{cid}]({url})" if url else cid
        lines.append(f"{i}. **{label}** — {g.get('hit_count', 0)} 段")
        for s in g.get("samples") or []:
            coord = s.get("coord") or ""
            ex = s.get("excerpt") or ""
            lines.append(f"   - {coord} {ex}…" if ex else f"   - {coord}")
        lines.append("")

    lines.append(
        "_完整逐條索引請用 [CBETA Online](https://cbetaonline.dila.edu.tw/) 關鍵字搜尋；"
        "本表僅含已匯入 pgvector 語料。_"
    )
    return "\n".join(lines)
