#!/usr/bin/env python3
"""Phase 2A: gateway E2E synthesis eval — citation validity & traceability."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

import psycopg

from canon.eval.citation_metrics import score_answer_citations
from canon.eval.run_eval import DEFAULT_DSN, load_golden
from canon.ingest.embed_client import embed_queries
from canon.query.pipeline import embed_text, plan_query, retrieve_with_plan
from canon.query.preprocess import preprocess_query

_THINKING_RE = re.compile(r"thinking process|redacted_thinking", re.I)
DEFAULT_GW = os.environ.get("VAJRA_GATEWAY_URL", "http://127.0.0.1:8081")


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _mean_optional(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return _mean(nums) if nums else None


def call_gateway(question: str, *, gateway_url: str, timeout: int) -> tuple[dict[str, Any], float]:
    body = json.dumps(
        {"mode": "canon_rag", "channel": "web", "message": question},
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        f"{gateway_url.rstrip('/')}/v1/task",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data, time.perf_counter() - t0


def evaluate_item(
    item: dict[str, Any],
    *,
    conn: psycopg.Connection,
    gateway_url: str,
    timeout: int,
    retrieval_k: int,
) -> dict[str, Any]:
    q = item["question"]
    pq = preprocess_query(q)
    plan = plan_query(pq)
    emb = embed_queries([embed_text(pq, plan)])[0]
    hits, _ = retrieve_with_plan(conn, pq, plan, emb)
    snippets = hits[:retrieval_k]

    try:
        gw_data, latency = call_gateway(q, gateway_url=gateway_url, timeout=timeout)
        err: str | None = None
    except error.URLError as exc:
        return {
            "id": item.get("id"),
            "category": item.get("category"),
            "question": q,
            "error": str(exc),
            "pass": False,
        }

    out = gw_data.get("output", {})
    answer = str(out.get("answer") or "")
    rag = gw_data.get("meta", {}).get("rag", {})
    cite_scores = score_answer_citations(conn, answer=answer, snippets=snippets)

    thinking_leak = bool(_THINKING_RE.search(answer))
    row: dict[str, Any] = {
        "id": item.get("id"),
        "category": item.get("category"),
        "question": q,
        "latency_sec": round(latency, 2),
        "query_type": rag.get("query_type"),
        "synthesis": rag.get("synthesis"),
        "rag_status": rag.get("status"),
        "answer_len": len(answer),
        "thinking_leak": thinking_leak,
        **cite_scores,
        "pass": (
            cite_scores["has_citation"]
            and cite_scores["all_citations_valid"]
            and cite_scores["all_citations_from_retrieval"]
            and not thinking_leak
            and not cite_scores["has_stray_canon_id"]
        ),
        "preview": answer[:200].replace("\n", " "),
    }
    if err:
        row["error"] = err
    return row


def run_synthesis_eval(
    golden_path: Path,
    *,
    dsn: str,
    gateway_url: str,
    timeout: int,
    retrieval_k: int,
    category: str | None,
    limit: int | None,
) -> dict[str, Any]:
    items = load_golden(golden_path)
    if category:
        cat = category.strip().upper()
        items = [it for it in items if str(it.get("category", "")).upper() == cat]
    if limit is not None and limit > 0:
        items = items[:limit]

    rows: list[dict[str, Any]] = []
    valid_rates: list[float | None] = []
    retrieval_rates: list[float | None] = []
    latencies: list[float] = []
    passes: list[float] = []
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)

    with psycopg.connect(dsn) as conn:
        for item in items:
            row = evaluate_item(
                item,
                conn=conn,
                gateway_url=gateway_url,
                timeout=timeout,
                retrieval_k=retrieval_k,
            )
            rows.append(row)
            cat = str(item.get("category", "?")).upper()
            by_category[cat].append(row)
            if row.get("error"):
                passes.append(0.0)
                continue
            valid_rates.append(row.get("citation_valid_rate"))
            retrieval_rates.append(row.get("citation_from_retrieval_rate"))
            latencies.append(float(row.get("latency_sec") or 0))
            passes.append(1.0 if row.get("pass") else 0.0)

    cat_report: dict[str, Any] = {}
    for cat, cat_rows in sorted(by_category.items()):
        vr = [r.get("citation_valid_rate") for r in cat_rows if not r.get("error")]
        rr = [r.get("citation_from_retrieval_rate") for r in cat_rows if not r.get("error")]
        cat_report[cat] = {
            "n": len(cat_rows),
            "pass_rate": _mean([1.0 if r.get("pass") else 0.0 for r in cat_rows]),
            "citation_valid_rate": _mean_optional(vr),
            "citation_from_retrieval_rate": _mean_optional(rr),
            "latency_avg_sec": _mean(
                [float(r.get("latency_sec") or 0) for r in cat_rows if not r.get("error")]
            ),
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eval": "synthesis_phase_2a_v1",
        "gateway": gateway_url,
        "n_questions": len(items),
        "pass_rate": _mean(passes) or 0.0,
        "citation_valid_rate": _mean_optional(valid_rates),
        "citation_from_retrieval_rate": _mean_optional(retrieval_rates),
        "latency_avg_sec": _mean(latencies),
        "targets": {
            "citation_valid_rate": 0.95,
            "citation_from_retrieval_rate": 0.90,
        },
        "by_category": cat_report,
        "results": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Gateway synthesis citation eval (Phase 2A)")
    p.add_argument(
        "--golden",
        type=Path,
        default=Path(__file__).resolve().parent / "golden_set.jsonl",
    )
    p.add_argument("--report", type=Path, default=None)
    p.add_argument("--gateway", default=DEFAULT_GW)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--retrieval-k", type=int, default=8)
    p.add_argument("--category", default=None)
    p.add_argument("--limit", type=int, default=None, help="Max questions (smoke)")
    p.add_argument(
        "--dsn",
        default=os.environ.get("VAJRA_CANON_PG_DSN", DEFAULT_DSN),
    )
    args = p.parse_args()

    report = run_synthesis_eval(
        args.golden,
        dsn=args.dsn,
        gateway_url=args.gateway,
        timeout=args.timeout,
        retrieval_k=args.retrieval_k,
        category=args.category,
        limit=args.limit,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
