"""Ingest checkpoint resume helpers."""

from canon.ingest.coord_chunker import Chunk
from canon.ingest.ingest import chunks_after_resume


def _chunk(coord_start: str, coord_end: str) -> Chunk:
    return Chunk(
        series="T",
        canon_id="T01n0001",
        coord_start=coord_start,
        coord_end=coord_end,
        text="x" * 200,
        char_len=200,
        file_path="/tmp/new.txt",
    )


def test_chunks_after_resume_skips_through_last_coord() -> None:
    chunks = [
        _chunk("T01n0001_p0001a01_", "T01n0001_p0001a05_"),
        _chunk("T01n0001_p0001a06_", "T01n0001_p0001a08_"),
        _chunk("T01n0001_p0001a09_", "T01n0001_p0001a12_"),
    ]
    resumed = chunks_after_resume(chunks, "T01n0001_p0001a08_")
    assert len(resumed) == 1
    assert resumed[0].coord_start == "T01n0001_p0001a09_"


def test_chunks_after_resume_empty_when_all_done() -> None:
    chunks = [_chunk("T01n0001_p0001a01_", "T01n0001_p0001a05_")]
    assert chunks_after_resume(chunks, "T01n0001_p0001a05_") == []
