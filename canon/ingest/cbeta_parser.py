"""Parse CBETA coordinate lines: ``coord##text``."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

_LINE_RE = re.compile(r"^(?P<coord>.*?)##(?P<text>.*)$")
_CANON_ID_RE = re.compile(r"^([A-Z]{1,3}\d+n\d+[a-zA-Z]?)_", re.I)


def parse_line(line: str) -> tuple[str | None, str]:
    """Return (coord, text). coord is None when line has no ``##`` marker."""
    line = line.rstrip("\n\r")
    m = _LINE_RE.match(line)
    if m:
        return m.group("coord").strip(), m.group("text").strip()
    return None, line.strip()


def canon_id_from_coord(coord: str) -> str:
    m = _CANON_ID_RE.match(coord.strip())
    if m:
        return m.group(1).upper()
    return coord.split("_", 1)[0].upper()


def iter_segments(path: Path) -> Iterator[tuple[str, str]]:
    """Yield (coord, text) for non-empty text lines."""
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            coord, text = parse_line(raw)
            if not text:
                continue
            if coord is None:
                continue
            yield coord, text
