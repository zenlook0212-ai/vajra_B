"""Strip markdown that causes inconsistent font sizes in Open WebUI."""

from __future__ import annotations

import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)", re.DOTALL)
_ATX_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_HR_RE = re.compile(r"^\s*---+\s*$", re.MULTILINE)


def sanitize_display_markdown(text: str) -> str:
    """Remove bold/heading/HR markers; keep plain text and [links](url)."""
    if not text:
        return text
    out = text
    for _ in range(8):
        nxt = _BOLD_RE.sub(r"\1", out)
        if nxt == out:
            break
        out = nxt
    for _ in range(8):
        nxt = _ITALIC_UNDERSCORE_RE.sub(r"\1", out)
        if nxt == out:
            break
        out = nxt
    out = _ATX_HEADING_RE.sub("", out)
    out = _HR_RE.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
