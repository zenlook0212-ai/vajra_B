"""Tests for D-class extractive synthesis."""

from canon.query.extractive_synth import fast_d_class_answer


def _sn(canon: str, coord: str, text: str) -> dict:
    return {
        "text": text,
        "metadata": {"canon_id": canon, "coord_start": coord},
    }


def test_fast_d_class_answer_requires_coords_and_two_aspects():
    snippets = [
        _sn("T01n0001", "T01n0001_p0001a05", "禁律、契經、法相為佛教三藏。"),
        _sn("T02n0147", "T02n0147_p0002b10", "比丘應持波羅提木叉，清淨梵行。"),
    ]
    out = fast_d_class_answer("佛經中如何說戒律？", snippets)
    assert out is not None
    assert "【義理面向】" in out
    assert "【綜合回答】" in out
    assert "【T01n0001_p0001a05】" in out
    assert "【T02n0147_p0002b10】" in out


def test_fast_d_class_answer_no_paren_canon_suffix():
    snippets = [
        _sn("T02n0125", "T02n0125_p0001a01", "緣起十二支為苦諦根本。"),
        _sn("T02n0147", "T02n0147_p0002b10", "比丘應持波羅提木叉，清淨梵行。"),
    ]
    out = fast_d_class_answer("十二因緣如何說？", snippets)
    assert out is not None
    assert "(T02N0125)" not in out
    assert "(T02n0125)" not in out


def test_fast_d_class_answer_returns_none_with_single_snippet():
    snippets = [_sn("T01n0001", "T01n0001_p0001a05", "單一片段。")]
    assert fast_d_class_answer("佛經中如何說戒律？", snippets) is None
