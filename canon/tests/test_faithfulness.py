"""Tests for faithfulness scoring."""

from canon.eval.faithfulness import faithfulness_pass, score_faithfulness_rules


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


def test_faithfulness_conservative_refusal_scores_one():
    answer = "現有語料不足以確認此問題的完整答案。"
    out = score_faithfulness_rules(answer, [])
    assert out["faithfulness"] == 1.0
    assert faithfulness_pass(out, answer=answer)


def test_faithfulness_pass_none_without_refusal():
    out = {"faithfulness": None}
    assert not faithfulness_pass(out, answer="一般回答但無引用。")
