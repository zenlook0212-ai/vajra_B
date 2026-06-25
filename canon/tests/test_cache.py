"""Tests for semantic answer cache validation."""

from canon.query.cache import is_stale_cached_answer


def test_stale_old_paren_canon_suffix():
    ans = "【義理面向】\n1. 【阿含經】緣起。【T02n0099_p0156c21_】(T02N0099)"
    assert is_stale_cached_answer(ans)


def test_stale_missing_summary_section():
    ans = "【義理面向】\n1. 【阿含經】緣起。【T02n0099_p0156c21_】"
    assert is_stale_cached_answer(ans)


def test_fresh_d_extractive_answer():
    ans = (
        "【義理面向】\n"
        "1. 【阿含經】緣起。【T02n0099_p0156c21_】\n"
        "2. 【阿含經】滅諦。【T02n0125_p0798a13_】\n\n"
        "【綜合回答】\n依檢索段落可從以下面向理解。"
    )
    assert not is_stale_cached_answer(ans)
