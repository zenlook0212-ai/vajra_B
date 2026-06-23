"""Tests for coord-first chunker."""

from canon.ingest.coord_chunker import MIN_CHARS, MAX_CHARS, chunk_segments


def test_merge_short_segments() -> None:
    segs = [
        ("T01n0001_p0001a01", "短。"),
        ("T01n0001_p0001a02", "也是短。"),
        ("T01n0001_p0001a03", "再補一些字讓合併後超過最小長度。" * 10),
    ]
    chunks = chunk_segments(segs, series="T", file_path="/tmp/new.txt")
    assert chunks
    assert chunks[0].canon_id == "T01N0001"
    assert chunks[0].coord_start == "T01n0001_p0001a01"
    assert all(c.char_len >= MIN_CHARS or len(segs) <= 2 for c in chunks)


def test_split_long_segment() -> None:
    long_text = "夫" + "法性深廣。" * 200
    segs = [("T01n0001_p0002a01", long_text)]
    chunks = chunk_segments(segs, series="T", file_path="/tmp/new.txt")
    assert len(chunks) > 1
    assert all(c.char_len <= MAX_CHARS + 20 for c in chunks)
