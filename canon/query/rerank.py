"""mxbai cross-encoder rerank via HTTP service."""

from __future__ import annotations

import os
from typing import Any

import httpx

RERANK_URL = os.environ.get("VAJRA_MXBAI_RERANK_URL", "http://127.0.0.1:8007/v1/rerank")
RERANK_MODEL = os.environ.get("VAJRA_MXBAI_RERANK_MODEL", "mixedbread-ai/mxbai-rerank-base-v2")


def rerank_snippets(
    query: str,
    snippets: list[dict[str, Any]],
    *,
    top_k: int = 5,
    url: str | None = None,
) -> list[dict[str, Any]]:
    if not snippets:
        return []
    docs = [str(s.get("text", "")) for s in snippets]
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": docs,
        "top_k": min(top_k, len(docs)),
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url or RERANK_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return snippets[:top_k]

    results = data.get("results", data.get("data", []))
    out: list[dict[str, Any]] = []
    for item in results:
        idx = item.get("index", item.get("document", {}).get("index"))
        if idx is None:
            continue
        sn = dict(snippets[int(idx)])
        sn["rerank_score"] = item.get("relevance_score", item.get("score"))
        out.append(sn)
    return out[:top_k] if out else snippets[:top_k]
