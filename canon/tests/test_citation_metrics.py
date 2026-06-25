"""Tests for Phase 2A citation metrics."""

from canon.eval.citation_metrics import (
    extract_citations,
    score_answer_citations,
    snippet_canon_ids,
    snippet_chunk_ids,
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
