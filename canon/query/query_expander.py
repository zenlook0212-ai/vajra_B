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

    # 阿含系開放題：補部類與常用經名檢索詞
    _agama_doctrines = (
        "緣起", "十二因緣", "四諦", "八正道", "無常", "無我", "涅槃", "中道", "阿羅漢",
    )
    if any(t in q for t in _agama_doctrines):
        if "阿含" not in terms:
            terms.append("阿含")
        for extra in ("長阿含經", "中阿含經", "雜阿含經", "增一阿含經"):
            if extra not in terms:
                terms.append(extra)

    if "菩提心" in q or ("菩提" in q and "菩提心" not in q):
        for extra in ("法華經", "華嚴經", "發菩提心", "願成佛", "菩薩發心"):
            if extra not in terms:
                terms.append(extra)

    if "無我" in q:
        for extra in ("阿含", "五蘊", "色受想行識", "非我", "金剛經"):
            if extra not in terms:
                terms.append(extra)

    if "淨土" in q:
        for extra in ("阿彌陀經", "極樂世界", "無量壽", "無量壽經", "觀無量壽經", "念佛", "西方極樂"):
            if extra not in terms:
                terms.append(extra)

    if "戒律" in q or "戒" in q:
        for extra in (
            "禁律",
            "律藏",
            "長阿含經序",
            "波羅提木叉",
            "波羅提木叉經",
            "戒經",
            "比丘戒",
            "梵行清淨",
            "增壹阿含",
        ):
            if extra not in terms:
                terms.append(extra)

    if "四諦" in q:
        for extra in ("苦諦", "集諦", "滅諦", "道諦", "四聖諦", "阿含"):
            if extra not in terms:
                terms.append(extra)

    if "空性" in q:
        for extra in ("色即是空", "心經", "金剛經", "般若", "śūnyatā"):
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

    if "中道" in q:
        for extra in (
            "八正道",
            "正見",
            "中阿含經",
            "般若",
            "八不中",
        ):
            if extra not in terms:
                terms.append(extra)

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
