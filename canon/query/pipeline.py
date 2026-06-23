"""Shared retrieval orchestration for gateway and eval (Phase A)."""

from __future__ import annotations

from typing import Any

import psycopg

from canon.query.preprocess import PreprocessedQuery
from canon.query.query_expander import expand_doctrine_terms, expand_scoped_terms
from canon.query.query_planner import QueryPlan, classify_query
from canon.query.retrieval import hybrid_search


def plan_query(pq: PreprocessedQuery) -> QueryPlan:
    return classify_query(pq)


def embed_text(pq: PreprocessedQuery, plan: QueryPlan) -> str:
    """D-class: original (白话语义). A/C: normalized (术语+经ID 利于 scoped 检索)."""
    if plan.query_type == "D":
        return pq.original
    return pq.normalized


def retrieve_with_plan(
    conn: psycopg.Connection,
    pq: PreprocessedQuery,
    plan: QueryPlan,
    embedding: list[float],
) -> tuple[list[dict[str, Any]], list[str] | None]:
    """Run hybrid search using QueryPlan; returns hits and sub_terms (if expanded)."""
    sub_terms: list[str] | None = None
    if plan.use_rule_expand:
        sub_terms = expand_doctrine_terms(pq.original)
    elif plan.query_type in ("A", "C"):
        sub_terms = expand_scoped_terms(pq.original)

    hits = hybrid_search(
        conn,
        bm25_query=pq.normalized,
        rerank_query=pq.original,
        embedding=embedding,
        series=pq.series_hint,
        canon_prefixes=pq.canon_prefixes or None,
        sub_terms=sub_terms,
        vec_top=plan.vec_top,
        bm25_top=plan.bm25_top,
        fuse_top=plan.fuse_top,
        rerank_top=plan.rerank_top,
        sub_term_bm25_top=plan.sub_term_bm25_top,
        doctrine_boost_prefixes=plan.doctrine_boost_prefixes or None,
    )
    return hits, sub_terms
