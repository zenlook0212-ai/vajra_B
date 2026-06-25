"""Tests for prompt budget helpers."""

from canon.query.prompt_budget import (
    estimate_tokens,
    llm_input_token_budget,
    truncate_to_token_budget,
)


def test_estimate_tokens_cjk():
    assert estimate_tokens("十二因緣") >= 2


def test_truncate_to_token_budget():
    long = "因" * 20000
    out = truncate_to_token_budget(long, 100)
    assert len(out) < len(long)
    assert out.endswith("…")


def test_llm_input_budget_leaves_reserve():
    b = llm_input_token_budget(reserve_output=1024)
    assert 500 < b < 8192
