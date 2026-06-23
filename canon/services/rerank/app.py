"""mxbai rerank HTTP service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

MODEL = os.environ.get("RERANK_MODEL", "mixedbread-ai/mxbai-rerank-base-v2")
_encoder: CrossEncoder | None = None

app = FastAPI()


class RerankRequest(BaseModel):
    model: str | None = None
    query: str
    documents: list[str]
    top_k: int = 5


def get_encoder() -> CrossEncoder:
    global _encoder
    if _encoder is None:
        _encoder = CrossEncoder(MODEL)
    return _encoder


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL}


@app.post("/v1/rerank")
def rerank(req: RerankRequest) -> dict[str, Any]:
    enc = get_encoder()
    pairs = [[req.query, d] for d in req.documents]
    scores = enc.predict(pairs)
    ranked = sorted(
        enumerate(scores),
        key=lambda x: float(x[1]),
        reverse=True,
    )[: req.top_k]
    return {
        "results": [
            {"index": int(i), "relevance_score": float(s)} for i, s in ranked
        ]
    }
