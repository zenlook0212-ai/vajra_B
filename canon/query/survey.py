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


_SURVEY_TEASER_CANONS = int(os.environ.get("VAJRA_SURVEY_TEASER_CANONS", "5"))


def primary_survey_keyword(query: str) -> str | None:
    """Doctrine term suitable for post-RAG survey teaser."""
    q = (query or "").strip()
    if not q:
        return None
    for key in sorted(TERM_MAP.keys(), key=len, reverse=True):
        if key in q:
            return key
    if q in TERM_MAP:
        return q
    return None


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
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, Any]:
    """Return grouped hits by canon_id with sample coords."""
    page = max(1, page)
    page_size = page_size or _SURVEY_MAX_CANONS
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

    all_ranked = sorted(
        by_canon.items(),
        key=lambda kv: (len(kv[1]), max(h.get("rank", 0) for h in kv[1])),
        reverse=True,
    )
    total_canon_count = len(all_ranked)
    total_pages = max(1, (total_canon_count + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    ranked = all_ranked[start : start + page_size]

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
        "total_canon_count": total_canon_count,
        "canon_count": len(groups),
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "groups": groups,
    }


def format_survey_teaser(
    report: dict[str, Any],
    *,
    cbeta_url_fn: Any,
    max_canons: int | None = None,
) -> str | None:
    """Short footer for canon_rag answers (B2)."""
    groups = report.get("groups") or []
    kw = report.get("query") or ""
    total_canons = int(report.get("total_canon_count") or report.get("canon_count") or 0)
    total_hits = int(report.get("total_hits") or 0)
    if not kw or total_canons < 2:
        return None
    # Only show when corpus has more sutras than this answer cited
    show = groups[: max_canons or _SURVEY_TEASER_CANONS]
    lines = [
        "",
        "---",
        f"**還有哪些經提及「{kw}」**（語料內約 **{total_canons}** 部、**{total_hits}** 段）",
    ]
    for g in show:
        cid = g.get("canon_id", "")
        url = cbeta_url_fn(cid) if cbeta_url_fn else None
        n = g.get("hit_count", 0)
        if url:
            lines.append(f"- [{cid}]({url})（{n} 段）")
        else:
            lines.append(f"- {cid}（{n} 段）")
    if total_canons > len(show):
        lines.append(
            f"- _另有 {total_canons - len(show)} 部經；完整列表請問："
            f"「列出『{kw}』全藏出處」_"
        )
    return "\n".join(lines)


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
    total_canons = report.get("total_canon_count", n_canon)
    page = report.get("page", 1)
    total_pages = report.get("total_pages", 1)

    lines = [
        f"【全藏出處】「{q}」",
        f"檢索詞：{'、'.join(terms)}；語料內共 **{total}** 段、**{total_canons}** 部經"
        f"（第 {page}/{total_pages} 頁，本頁 {n_canon} 部；已匯入 corpus；非 CBETA 官網全庫）。",
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
