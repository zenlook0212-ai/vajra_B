"""Tests for RRF fusion."""

from canon.query.retrieval import rrf_fuse


def test_rrf_fuse_orders_union() -> None:
    vec_ranks = {1: 1, 2: 5}
    bm25_ranks = {2: 1, 3: 3}
    chunk_canon = {1: "T01N0001", 2: "T02N0123", 3: "T03N0001"}
    fused = rrf_fuse(vec_ranks, bm25_ranks, query="T02N0123", chunk_canon=chunk_canon)
    ids = [cid for cid, _ in fused]
    assert 2 in ids
    assert ids[0] == 2  # canon bonus + dual rank


def test_rrf_single_source() -> None:
    vec_ranks = {10: 1, 11: 2}
    fused = rrf_fuse(vec_ranks, {}, query="空性", chunk_canon={10: "T08N0001", 11: "T08N0002"})
    assert [cid for cid, _ in fused] == [10, 11]
