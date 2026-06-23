"""OpenAI-compatible embedding client for ingest and query."""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx

DEFAULT_EMBED_URL = os.environ.get(
    "VAJRA_QWEN_EMBED_URL", "http://127.0.0.1:8005/v1/embeddings"
)
DEFAULT_MODEL_ID = os.environ.get(
    "VAJRA_QWEN_EMBED_MODEL", "Qwen3-Embedding-4B"
)
EMBED_DIM = int(os.environ.get("VAJRA_CANON_EMBED_DIM", "2048"))

InputType = Literal["query", "document"]


def embed_texts(
    texts: list[str],
    *,
    url: str | None = None,
    model_id: str | None = None,
    timeout: float = 600.0,
    input_type: InputType | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    payload: dict[str, Any] = {
        "model": model_id or DEFAULT_MODEL_ID,
        "input": texts,
    }
    if EMBED_DIM:
        payload["dimensions"] = EMBED_DIM
    if input_type:
        payload["input_type"] = input_type

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url or DEFAULT_EMBED_URL, json=payload)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    out: list[list[float]] = []
    for item in sorted(data, key=lambda x: x.get("index", 0)):
        vec = item.get("embedding")
        if not isinstance(vec, list):
            raise ValueError("missing embedding in response")
        if EMBED_DIM and len(vec) != EMBED_DIM:
            if len(vec) > EMBED_DIM:
                vec = vec[:EMBED_DIM]
            else:
                raise ValueError(f"expected dim {EMBED_DIM}, got {len(vec)}")
        out.append([float(x) for x in vec])
    return out


def embed_queries(texts: list[str], **kwargs: Any) -> list[list[float]]:
    return embed_texts(texts, input_type="query", **kwargs)


def embed_passages(texts: list[str], **kwargs: Any) -> list[list[float]]:
    return embed_texts(texts, input_type="document", **kwargs)


def probe_embedding_dim(
    *,
    url: str | None = None,
    model_id: str | None = None,
) -> int:
    vecs = embed_queries(["dimension probe"], url=url, model_id=model_id)
    return len(vecs[0])
