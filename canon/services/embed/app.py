"""Qwen3-Embedding-4B OpenAI-compatible /v1/embeddings service."""

from __future__ import annotations

import os
from typing import Any, Literal

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_PATH = os.environ.get("EMBED_MODEL", "/data/models/Qwen3-Embedding-4B")
EMBED_DIM = int(os.environ.get("VAJRA_CANON_EMBED_DIM", "2048"))

_model: SentenceTransformer | None = None
_loading = False

app = FastAPI()


class EmbeddingsRequest(BaseModel):
    model: str | None = None
    input: str | list[str]
    dimensions: int | None = None
    input_type: Literal["query", "document"] | None = None


def _device() -> str:
    forced = os.environ.get("EMBED_DEVICE", "").strip()
    if forced:
        return forced
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model() -> SentenceTransformer:
    global _model, _loading
    if _model is not None:
        return _model
    if _loading:
        raise RuntimeError("model is still loading")
    _loading = True
    try:
        _model = SentenceTransformer(MODEL_PATH, trust_remote_code=True, device=_device())
        return _model
    finally:
        _loading = False


def _encode(texts: list[str], *, input_type: str | None, dim: int) -> Any:
    enc = load_model()
    kwargs: dict[str, Any] = {
        "normalize_embeddings": True,
        "truncate_dim": dim,
        "batch_size": min(32, len(texts)),
        "show_progress_bar": False,
    }
    if input_type == "query":
        try:
            return enc.encode(texts, prompt_name="query", **kwargs)
        except Exception:
            texts = [
                f"Instruct: Retrieve Buddhist canon passages for this query\nQuery: {t}"
                for t in texts
            ]
    elif input_type == "document":
        try:
            return enc.encode(texts, prompt_name="document", **kwargs)
        except Exception:
            pass
    return enc.encode(texts, **kwargs)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "model": MODEL_PATH,
        "device": _device(),
        "loaded": str(_model is not None),
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"data": [{"id": "Qwen3-Embedding-4B", "object": "model"}]}


@app.post("/v1/embeddings")
def embeddings(req: EmbeddingsRequest) -> dict[str, Any]:
    texts = req.input if isinstance(req.input, list) else [req.input]
    dim = req.dimensions or EMBED_DIM
    vectors = _encode(texts, input_type=req.input_type, dim=dim)
    data = [
        {
            "object": "embedding",
            "index": i,
            "embedding": [float(x) for x in vec.tolist()],
        }
        for i, vec in enumerate(vectors)
    ]
    return {"object": "list", "data": data, "model": req.model or "Qwen3-Embedding-4B"}
