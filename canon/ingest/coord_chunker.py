"""Coord-first chunking for CBETA text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from canon.ingest.cbeta_parser import canon_id_from_coord

MIN_CHARS = 120
MAX_CHARS = 600
OVERLAP = 60

_SENT_SPLIT_RE = re.compile(r"(?<=[。！？\n])")


@dataclass(frozen=True)
class Chunk:
    series: str
    canon_id: str
    coord_start: str
    coord_end: str
    text: str
    char_len: int
    file_path: str


def _split_long_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts = [p for p in _SENT_SPLIT_RE.split(text) if p]
    if len(parts) <= 1:
        out: list[str] = []
        i = 0
        while i < len(text):
            out.append(text[i : i + max_chars])
            i += max(max_chars - overlap, 1)
        return out

    chunks: list[str] = []
    buf = ""
    for part in parts:
        if len(buf) + len(part) <= max_chars:
            buf += part
        else:
            if buf:
                chunks.append(buf)
            buf = part
    if buf:
        chunks.append(buf)
    return chunks


def _emit_pieces(
    out: list[Chunk],
    *,
    series: str,
    file_path: str,
    coord_start: str,
    coord_end: str,
    text: str,
) -> None:
    cid = canon_id_from_coord(coord_start)
    for piece in _split_long_text(text):
        out.append(
            Chunk(
                series=series,
                canon_id=cid,
                coord_start=coord_start,
                coord_end=coord_end,
                text=piece,
                char_len=len(piece),
                file_path=file_path,
            )
        )


def chunk_segments(
    segments: list[tuple[str, str]],
    *,
    series: str,
    file_path: str,
) -> list[Chunk]:
    """Merge short coord segments; split long merged text by sentence."""
    if not segments:
        return []

    out: list[Chunk] = []
    buf_coords: list[str] = []
    buf_texts: list[str] = []

    def flush() -> None:
        nonlocal buf_coords, buf_texts
        if not buf_coords:
            return
        merged = "".join(buf_texts)
        _emit_pieces(
            out,
            series=series,
            file_path=file_path,
            coord_start=buf_coords[0],
            coord_end=buf_coords[-1],
            text=merged,
        )
        buf_coords = []
        buf_texts = []

    for coord, text in segments:
        if not buf_coords:
            buf_coords = [coord]
            buf_texts = [text]
            continue

        merged_len = sum(len(t) for t in buf_texts) + len(text)
        if merged_len <= MAX_CHARS:
            buf_coords.append(coord)
            buf_texts.append(text)
            if merged_len >= MIN_CHARS:
                flush()
            continue

        buf_len = sum(len(t) for t in buf_texts)
        if buf_len >= MIN_CHARS:
            flush()
            buf_coords = [coord]
            buf_texts = [text]
        else:
            combined = "".join(buf_texts) + text
            _emit_pieces(
                out,
                series=series,
                file_path=file_path,
                coord_start=buf_coords[0],
                coord_end=coord,
                text=combined,
            )
            buf_coords = []
            buf_texts = []

    if buf_coords:
        merged = "".join(buf_texts)
        if len(merged) < MIN_CHARS and out:
            prev = out[-1]
            combined = prev.text + merged
            if len(combined) <= MAX_CHARS:
                out[-1] = Chunk(
                    series=prev.series,
                    canon_id=prev.canon_id,
                    coord_start=prev.coord_start,
                    coord_end=buf_coords[-1],
                    text=combined,
                    char_len=len(combined),
                    file_path=file_path,
                )
            else:
                flush()
        else:
            flush()

    return out
