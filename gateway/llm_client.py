"""Async OpenAI-compatible vLLM client with concurrency cap and retries."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, cast

import httpx
from gateway.config import vllm_chat_timeout_sec, vllm_embed_timeout_sec
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONCURRENT = int(os.environ.get("VAJRA_GATEWAY_MAX_CONCURRENT", "2"))
_LLM_SEMAPHORE = asyncio.Semaphore(_DEFAULT_MAX_CONCURRENT)


@asynccontextmanager
async def acquire_llm_slot() -> AsyncIterator[None]:
    """Serialize heavy LLM HTTP calls (shared with chat_completion)."""
    async with _LLM_SEMAPHORE:
        yield


async def embeddings_request(
    client: httpx.AsyncClient,
    *,
    url: str,
    model_id: str,
    input_text: str,
    input_type: str | None = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """POST /v1/embeddings style payload."""
    payload: dict[str, Any] = {
        "model": model_id,
        "input": input_text,
    }
    if input_type:
        payload["input_type"] = input_type
    tmo = timeout_sec if timeout_sec is not None else vllm_embed_timeout_sec()
    async with _LLM_SEMAPHORE:
        resp = await client.post(url, json=payload, timeout=tmo)
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def chat_completion(
    client: httpx.AsyncClient,
    *,
    url: str,
    model_id: str,
    messages: list[dict[str, str]],
    max_tokens: int = 2048,
    temperature: float = 0.2,
    timeout_sec: float | None = None,
    extra_body: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (assistant plain text content, raw JSON)."""
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra_body:
        payload.update(extra_body)

    tmo = timeout_sec if timeout_sec is not None else vllm_chat_timeout_sec()
    async with _LLM_SEMAPHORE:
        response = await client.post(url, json=payload, timeout=tmo)
        response.raise_for_status()
        data = cast(dict[str, Any], response.json())

    choices = data.get("choices") or []
    if not choices:
        return "", data
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    if not isinstance(content, str):
        return str(content), data
    return content.strip(), data
