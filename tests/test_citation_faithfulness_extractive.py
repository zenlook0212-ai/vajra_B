"""Synthesis eval fixes: citation stray, refusal pass, extractive coords."""

from canon.eval.citation_metrics import (
    is_conservative_refusal,
    strip_citation_blocks,
)
from canon.eval.faithfulness import faithfulness_pass, score_faithfulness_rules
from canon.query.extractive_synth import fast_d_class_answer


def test_citation_strip_and_refusal_exports():
    assert is_conservative_refusal("語料不足，無法回答。")
    assert "T08N0223" not in strip_citation_blocks("【T08n0223_p1_】(T08N0223)")


def test_faithfulness_conservative_refusal_pass():
    answer = "無法從現有語料確認。"
    scores = score_faithfulness_rules(answer, [])
    assert scores["faithfulness"] == 1.0
    assert faithfulness_pass(scores, answer=answer)


def test_extractive_no_paren_suffix():
    snippets = [
        {
            "text": "緣起為苦諦根本。",
            "metadata": {"canon_id": "T02n0125", "coord_start": "T02n0125_p0001a01"},
        },
        {
            "text": "比丘應持戒。",
            "metadata": {"canon_id": "T02n0147", "coord_start": "T02n0147_p0002b10"},
        },
    ]
    out = fast_d_class_answer("因緣？", snippets)
    assert out is not None
    assert "(T02" not in out
