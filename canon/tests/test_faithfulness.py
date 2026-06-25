"""Tests for faithfulness scoring."""

from canon.eval.faithfulness import score_faithfulness_rules


def test_faithfulness_high_overlap():
    snippets = [{"text": "如來出世大教有三種禁律契經法相", "metadata": {}}]
    answer = "序文說如來出世大教有三，分別為禁律、契經與法相。【T01n0001_p0001a07_】"
    out = score_faithfulness_rules(answer, snippets)
    assert out["faithfulness"] is not None
    assert out["faithfulness"] >= 0.5


def test_faithfulness_detects_unsupported():
    snippets = [{"text": "完全不同的內容在這裡", "metadata": {}}]
    answer = (
        "這是一段與檢索完全無關的虛構佛學論述，"
        "聲稱佛陀在某處宣說了從未出現的教法。"
    )
    out = score_faithfulness_rules(answer, snippets)
    assert out["faithfulness"] is not None
    assert out["faithfulness"] < 0.5
    assert out["unsupported_sentences"]
