#!/usr/bin/env python3
"""Weekly eval harness for canon RAG."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from canon.eval.citation_metrics import citation_exists, normalize_citation_coord
from canon.ingest.embed_client import embed_queries
from canon.query.pipeline import embed_text, plan_query, retrieve_with_plan
from canon.query.preprocess import normalize_canon_prefix, preprocess_query

from canon.eval.citation_metrics import _COORD_CITE_RE


def load_golden(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def item_expected_canons(item: dict[str, Any]) -> list[str]:
    if ids := item.get("expected_canon_ids"):
        return list(ids)
    if cid := item.get("expected_canon_id"):
        return [str(cid)]
    return []


def canon_ids_match(expected: str, got: str) -> bool:
    exp = normalize_canon_prefix(expected) or expected.strip().upper()
    g = normalize_canon_prefix(got) or got.strip().upper()
    return exp == g or g.startswith(exp)


def hit_canon_id(hits: list[dict[str, Any]], expected_canons: list[str], k: int) -> bool:
    if not expected_canons:
        return False
    for h in hits[:k]:
        cid = str(h.get("canon_id", ""))
        meta = h.get("metadata") or {}
        meta_cid = str(meta.get("canon_id", ""))
        for expected in expected_canons:
            if canon_ids_match(expected, cid) or canon_ids_match(expected, meta_cid):
                return True
    return False


def recall_at_k(hits: list[dict[str, Any]], expected_canons: list[str], k: int = 5) -> bool:
    return hit_canon_id(hits, expected_canons, k)


def _canon_from_hit(h: dict[str, Any]) -> str:
    cid = str(h.get("canon_id", ""))
    if cid:
        return cid
    meta = h.get("metadata") or {}
    return str(meta.get("canon_id", ""))


def infer_miss_reason(
    *,
    expected_canons: list[str],
    hits: list[dict[str, Any]],
    sub_terms: list[str] | None,
) -> str:
    if not hits:
        return "no_hits"
    retrieved = [_canon_from_hit(h) for h in hits[:10] if _canon_from_hit(h)]
    if not retrieved:
        return "empty_canon_ids"

    exp_families = {normalize_canon_prefix(c) or c[:3].upper() for c in expected_canons}
    got_families = {r[:3].upper() for r in retrieved}

    if exp_families & got_families:
        return "wrong_volume_same_family"

    agama_expected = any(c.startswith("T01") or c.startswith("T02") for c in expected_canons)
    abhidharma_got = any(r.startswith("T38") or r.startswith("T42") for r in retrieved)
    if agama_expected and abhidharma_got:
        return "wrong_corpus_family"

    if not sub_terms:
        return "semantic_drift"
    return "bm25_and_vector_miss"


def diagnose_item(
    item: dict[str, Any],
    hits: list[dict[str, Any]],
    *,
    sub_terms: list[str] | None,
    plan: Any,
    k: int,
) -> dict[str, Any]:
    expected = item_expected_canons(item)
    retrieved = [_canon_from_hit(h) for h in hits[:10]]
    hit = hit_canon_id(hits, expected, k)
    return {
        "id": item.get("id"),
        "category": item.get("category"),
        "query": item.get("question"),
        "query_type": plan.query_type,
        "sub_terms": sub_terms,
        "expected_canon_ids": expected,
        "retrieved_canon_ids": retrieved,
        "hit": hit,
        "miss_reason": None if hit else infer_miss_reason(
            expected_canons=expected,
            hits=hits,
            sub_terms=sub_terms,
        ),
        "plan": {
            "vec_top": plan.vec_top,
            "rerank_top": plan.rerank_top,
            "doctrine_boost": plan.doctrine_boost_prefixes,
        },
    }

DEFAULT_DSN = "postgresql://vajra:vajra@127.0.0.1:5433/canon"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_eval(
    golden_path: Path,
    *,
    dsn: str,
    k: int = 5,
    category: str | None = None,
    diagnose: bool = False,
) -> dict[str, Any]:
    items = load_golden(golden_path)
    if category:
        cat_filter = category.strip().upper()
        items = [it for it in items if str(it.get("category", "")).upper() == cat_filter]

    recalls: list[float] = []
    citations: list[float] = []
    by_category: dict[str, list[float]] = defaultdict(list)
    diagnoses: list[dict[str, Any]] = []

    with psycopg.connect(dsn) as conn:
        for item in items:
            q = item["question"]
            expected = item_expected_canons(item)
            pq = preprocess_query(q)
            plan = plan_query(pq)
            emb = embed_queries([embed_text(pq, plan)])[0]
            hits, sub_terms = retrieve_with_plan(conn, pq, plan, emb)
            hit = 1.0 if recall_at_k(hits, expected, k=k) else 0.0
            recalls.append(hit)
            cat = str(item.get("category", "unknown")).upper()
            by_category[cat].append(hit)

            if diagnose:
                diagnoses.append(
                    diagnose_item(item, hits, sub_terms=sub_terms, plan=plan, k=k)
                )

            for m in _COORD_CITE_RE.finditer(item.get("sample_answer", "")):
                citations.append(1.0 if citation_exists(conn, m.group(1)) else 0.0)

    recall_key = f"recall@{k}"
    category_report = {
        cat: {
            "n": len(vals),
            recall_key: _mean(vals),
        }
        for cat, vals in sorted(by_category.items())
    }
    ab = by_category.get("A", []) + by_category.get("B", [])
    abc = ab + by_category.get("C", [])
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "golden_version": "v2",
        "retrieval_version": "phase_a6_v1",
        "n_questions": len(items),
        recall_key: _mean(recalls) or 0.0,
        f"{recall_key}_AB_only": _mean(ab),
        f"{recall_key}_ABC_only": _mean(abc),
        "citation_accuracy": _mean(citations),
        "faithfulness": None,
        "by_category": category_report,
    }
    if diagnose:
        report["diagnoses"] = diagnoses
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--golden",
        type=Path,
        default=Path(__file__).resolve().parent / "golden_set.jsonl",
    )
    p.add_argument("--report", type=Path, default=None)
    p.add_argument("--k", type=int, default=5)
    p.add_argument(
        "--category",
        default=None,
        help="Filter golden items by category (e.g. D)",
    )
    p.add_argument(
        "--diagnose",
        action="store_true",
        help="Include per-question retrieval diagnostics",
    )
    p.add_argument(
        "--dsn",
        default=os.environ.get("VAJRA_CANON_PG_DSN", DEFAULT_DSN),
    )
    args = p.parse_args()
    report = run_eval(
        args.golden,
        dsn=args.dsn,
        k=args.k,
        category=args.category,
        diagnose=args.diagnose,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
