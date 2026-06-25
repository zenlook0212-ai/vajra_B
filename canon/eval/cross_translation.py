"""Detect forbidden cross-translation term hard-mapping in 【綜合回答】."""

from __future__ import annotations

import re

_SUMMARY_HEAD = "【綜合回答】"

_HARD_MAP_RE = re.compile(
    r"[「『][^」』]{1,16}[」』]\s*即\s*[「『]?[^，。；\n]{1,16}|"
    r"即觸|即触|即受|即取|A\s*即\s*B|等同於|等同为",
    re.I,
)


def summary_section(answer: str) -> str:
    text = answer or ""
    if _SUMMARY_HEAD not in text:
        return text
    body = text.split(_SUMMARY_HEAD, 1)[1]
    for stop in ("【還有哪些經", "---", "【CBETA 連結】"):
        if stop in body:
            body = body.split(stop, 1)[0]
    return body


def cross_translation_violations(answer: str) -> list[str]:
    section = summary_section(answer)
    if not section.strip():
        return []
    hits: list[str] = []
    for m in _HARD_MAP_RE.finditer(section):
        frag = m.group(0).strip()
        if frag and frag not in hits:
            hits.append(frag)
    return hits


def cross_translation_ok(answer: str) -> bool:
    return not cross_translation_violations(answer)
