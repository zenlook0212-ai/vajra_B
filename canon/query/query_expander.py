"""Rule-based doctrine term expansion for D-class retrieval (Phase A)."""

from __future__ import annotations

import re

from canon.query.preprocess import TERM_MAP

_STRIP_PATTERNS = (
    r"佛經中如何說",
    r"佛經中怎麼說",
    r"佛經中如何記載",
    r"佛經中",
    r"如何說",
    r"怎麼說",
    r"如何記載",
    r"請問",
    r"請解釋",
    r"什麼是",
    r"何謂",
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _strip_filler(text: str) -> str:
    q = text.strip().rstrip("？?")
    for pat in _STRIP_PATTERNS:
        q = re.sub(pat, "", q)
    return q.strip("？? 的")


def expand_doctrine_terms(query: str) -> list[str]:
    """Extract doctrine keywords and TERM_MAP expansions for multi-path BM25."""
    q = query.strip()
    terms: list[str] = []
    matched_spans: list[tuple[int, int]] = []

    for term in sorted(TERM_MAP.keys(), key=len, reverse=True):
        start = q.find(term)
        if start < 0:
            continue
        span = (start, start + len(term))
        if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in matched_spans):
            continue
        matched_spans.append(span)
        if term not in terms:
            terms.append(term)
        for alt in TERM_MAP[term]:
            if _CJK_RE.search(alt) and alt not in terms:
                terms.append(alt)

    # 阿含系開放題：補一條部類檢索詞（緣起/四諦等基礎教義）
    if any(t in q for t in ("緣起", "十二因緣", "四諦", "八正道", "無常", "無我", "涅槃")):
        if "阿含" not in terms:
            terms.append("阿含")

    if "淨土" in q:
        for extra in ("阿彌陀經", "極樂世界", "無量壽"):
            if extra not in terms:
                terms.append(extra)

    if "戒律" in q or "戒" in q:
        for extra in ("波羅提木叉", "戒經", "比丘戒"):
            if extra not in terms:
                terms.append(extra)

    if "禪定" in q or "禪那" in q:
        for extra in ("坐禪", "入定", "壇經", "六祖"):
            if extra not in terms:
                terms.append(extra)

    if "十二因緣" in q:
        for extra in ("無明", "老死", "生滅"):
            if extra not in terms:
                terms.append(extra)

    if "緣起" in q and "因緣" not in terms:
        terms.append("因緣")

    if not terms:
        stripped = _strip_filler(q)
        if stripped:
            terms.append(stripped)

    if not terms:
        return [q]

    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


_SCOPED_STRIP = _STRIP_PATTERNS + (
    r"中",
    r"之作",
    r"的",
    r"說",
)


def expand_scoped_terms(query: str) -> list[str]:
    """Keyword supplements for A/C scoped queries (BM25 often sparse on Chinese)."""
    from canon.query.preprocess import CANON_ALIASES

    q = query.strip().rstrip("？?")
    terms: list[str] = []
    for alias in sorted(CANON_ALIASES, key=len, reverse=True):
        if alias in q and alias not in terms:
            terms.append(alias)
    stripped = q
    for pat in _SCOPED_STRIP:
        stripped = re.sub(pat, " ", stripped)
    for part in re.split(r"\s+", stripped):
        part = part.strip("？? ")
        if 2 <= len(part) <= 8 and part not in terms:
            terms.append(part)
    if not terms:
        return [q[:8]] if len(q) >= 2 else [q]
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:5]
