"""Tests for cross-translation eval guard."""

from canon.eval.cross_translation import cross_translation_ok, cross_translation_violations


def test_ok_when_no_hard_mapping():
    ans = "【綜合回答】\n不同譯本用字不同，順序相近，不宜逕判同一支。"
    assert cross_translation_ok(ans)


def test_fail_on_quoted_hard_map():
    ans = "【綜合回答】\n「更樂」即觸、「痛」即受。"
    assert not cross_translation_ok(ans)
    assert cross_translation_violations(ans)


def test_only_checks_summary_section():
    ans = "1. 【雜阿含 T99】更樂緣痛。【T02n0125_p0819c18】\n\n【綜合回答】\n僅述用字不同。"
    assert cross_translation_ok(ans)
