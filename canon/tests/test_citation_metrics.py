"""Tests for Phase 2A citation metrics."""

from canon.eval.citation_metrics import (
    citation_from_retrieval,
    extract_canon_ids,
    extract_citations,
    is_conservative_refusal,
    score_answer_citations,
    snippet_canon_ids,
    snippet_chunk_ids,
    strip_citation_blocks,
)


def _sn(chunk_id: int, canon: str, coord: str, text: str = "x") -> dict:
    return {
        "id": chunk_id,
        "canon_id": canon,
        "text": text,
        "metadata": {"canon_id": canon, "coord_start": coord, "coord_end": f"{coord.rstrip('_')}z"},
    }


def test_extract_citations():
    ans = "依【T01n0001_p0001a07_】及【T01n0001_p0001a08_】"
    assert len(extract_citations(ans)) == 2


def test_snippet_helpers():
    snippets = [_sn(1, "T01N0001", "T01n0001_p0001a07_")]
    assert snippet_chunk_ids(snippets) == {1}
    assert "T01N0001" in snippet_canon_ids(snippets)


def test_score_no_citations():
    class FakeConn:
        pass

    out = score_answer_citations(FakeConn(), answer="無坐標", snippets=[])
    assert out["n_citations"] == 0
    assert out["has_citation"] is False


def test_strip_citation_blocks_removes_paren_canon_suffix():
    ans = "段落【T08n0223_p0001a01_】(T08N0223)後文"
    stripped = strip_citation_blocks(ans)
    assert "T08N0223" not in stripped
    assert extract_canon_ids(stripped) == []


def test_strip_citation_blocks_removes_aspect_headers():
    ans = "1. 【阿含／長部】如是不聞"
    stripped = strip_citation_blocks(ans)
    assert "／" not in stripped
    assert extract_canon_ids(stripped) == []


def test_no_stray_from_paren_after_coord():
    class FakeConn:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return (99,)

    snippets = [_sn(5, "T08N0223", "T08n0223_p0001a01_")]
    answer = "依【T08n0223_p0001a01_】(T08N0223)所載"
    out = score_answer_citations(
        FakeConn(),
        answer=answer,
        snippets=snippets,
        trace_snippets=snippets,
    )
    assert out["has_stray_canon_id"] is False


def test_citation_from_retrieval_volume_match():
    snippets = [_sn(99, "T08N0223", "T08n0223_p0001a01_")]
    retrieved_ids = snippet_chunk_ids(snippets)
    retrieved_canons = snippet_canon_ids(snippets)
    assert citation_from_retrieval(
        chunk_id=42,
        coord="T08n0223_p0002b01_",
        retrieved_ids=retrieved_ids,
        retrieved_canons=retrieved_canons,
    )


def test_is_conservative_refusal():
    assert is_conservative_refusal("現有語料不足以確認此問題。")
    assert is_conservative_refusal("無法從現有語料得出結論")
    assert not is_conservative_refusal("依經文所述，四諦為根本教法。")
