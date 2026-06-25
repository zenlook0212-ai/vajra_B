"""Tests for D-class extractive synthesis."""

from canon.query.extractive_synth import (
    _clean_snippet_text,
    _excerpt_polished,
    assemble_hybrid_d_answer,
    d_synth_mode,
    fast_d_class_answer,
    format_d_aspects_body,
    sanitize_hybrid_summary,
)


def _sn(canon: str, coord: str, text: str) -> dict:
    return {
        "text": text,
        "metadata": {"canon_id": canon, "coord_start": coord},
    }


def test_clean_snippet_strips_html_and_notes():
    raw = "<p>繫念在前[05]，緣無明行，緣行識[06]，識滅則名色滅。"
    assert "[05]" not in _clean_snippet_text(raw)
    assert "<p>" not in _clean_snippet_text(raw)


def test_excerpt_polish_drops_trailing_fragment():
    raw = "十二因緣難見難知，諸天魔梵沙門婆羅門未見緣者，則皆荒迷，無能見者。阿"
    out = _excerpt_polished(raw, max_chars=200)
    assert out.endswith("。")
    assert not out.endswith("。阿")
    long_chain = (
        "繫念在前，於十二因緣逆順觀察，所謂是事有故是事有，"
        "是事起故是事起，謂緣無明行，緣行識，緣識名色，緣名色六入處，"
        "緣六入處觸，緣觸受，緣受愛，緣愛取，緣取有，緣有生，"
        "緣生老死憂悲惱苦如是純大苦聚集"
    )
    out = _excerpt_polished(long_chain, max_chars=80)
    assert out.endswith(("。", "；", "！", "？", "，", "…"))
    assert not out.endswith("識滅")


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


def test_summary_uses_labels_not_raw_fragments():
    snippets = [
        _sn(
            "T02n0099",
            "T02n0099_p0156c21",
            "<p>繫念在前[05]，緣無明行，緣行識，緣識名色，緣名色六入處。</p>",
        ),
        _sn(
            "T01n0001",
            "T01n0001_p0060b07",
            "十二因緣法之光明，甚深難解，諸天魔梵難見難知。",
        ),
    ]
    out = fast_d_class_answer("十二因緣", snippets)
    assert out is not None
    summary = out.split("【綜合回答】", 1)[1]
    assert "依檢索語料" in summary
    assert "雜阿含 T99" in out or "阿含部" in out
    assert "<p>" not in summary
    assert "[05]" not in summary
    assert "；繫念在前" not in summary


def test_d_synth_mode_hybrid_default(monkeypatch):
    monkeypatch.delenv("VAJRA_RAG_D_SYNTH", raising=False)
    monkeypatch.delenv("VAJRA_RAG_FAST_D_SYNTH", raising=False)
    assert d_synth_mode() == "hybrid"


def test_sanitize_hybrid_summary_strips_unknown_coords():
    aspects = "【義理面向】\n1. 【雜阿含 T99】緣起。【T02n0099_p0156c21_】"
    summary = "綜述。【T02n0099_p0156c21_】【T99n9999_p0001a01_】"
    out = sanitize_hybrid_summary(summary, aspects)
    assert "T02n0099" in out
    assert "T99n9999" not in out


def test_assemble_hybrid_d_answer():
    body = format_d_aspects_body(
        [
            "1. 【雜阿含 T99】緣起。【T02n0099_p0156c21_】",
            "2. 【增一阿含 T125】滅諦。【T02n0125_p0798a13_】",
        ]
    )
    out = assemble_hybrid_d_answer(body, "十二因緣順逆觀為核心。【T02n0099_p0156c21_】")
    assert "【義理面向】" in out
    assert "【綜合回答】" in out
    assert out.index("【義理面向】") < out.index("【綜合回答】")
