"""Token/char budgets for qwen35b max-model-len=8192."""

from __future__ import annotations

import os

# Conservative CJK estimate: ~1 token per 1.5 chars (mixed text often higher).
_CHARS_PER_TOKEN = float(os.environ.get("VAJRA_CHARS_PER_TOKEN", "1.5"))


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def truncate_chars(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def truncate_to_token_budget(text: str, max_tokens: int) -> str:
    max_chars = max(64, int(max_tokens * _CHARS_PER_TOKEN))
    return truncate_chars(text, max_chars)


def llm_context_limit() -> int:
    try:
        return int(os.environ.get("VAJRA_LLM_CONTEXT", "8192"))
    except ValueError:
        return 8192


def llm_input_token_budget(*, reserve_output: int | None = None) -> int:
    """Input budget leaving room for model output + template overhead."""
    ctx = llm_context_limit()
    reserve = reserve_output
    if reserve is None:
        try:
            reserve = int(os.environ.get("VAJRA_LLM_OUTPUT_RESERVE", "1024"))
        except ValueError:
            reserve = 1024
    overhead = int(os.environ.get("VAJRA_LLM_TEMPLATE_OVERHEAD", "256"))
    return max(512, ctx - reserve - overhead)


def webui_context_budget() -> int:
    try:
        return int(os.environ.get("VAJRA_WEBUI_CTX_BUDGET", "6800"))
    except ValueError:
        return 6800
