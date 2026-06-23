"""Query preprocessing: term mapping, canon normalization, intent."""

from __future__ import annotations

import re
from dataclasses import dataclass

TERM_MAP: dict[str, list[str]] = {
    "般若": ["智慧", "prajñā", "prajna", "prajnaparamita", "波羅蜜", "波羅密"],
    "空性": ["śūnyatā", "sunyata", "空", "空相", "真空"],
    "緣起": ["pratītyasamutpāda", "pratityasamutpada", "十二因緣", "因緣"],
    "十二因緣": ["緣起", "因緣", "十二緣起"],
    "涅槃": ["nirvāṇa", "nirvana", "泥洹"],
    "菩提心": ["菩提", "發心", "願菩提心", "bodhicitta"],
    "菩提": ["bodhi", "覺", "阿耨多羅", "菩提心"],
    "四諦": ["苦諦", "集諦", "滅諦", "道諦"],
    "八正道": ["正見", "正思惟", "正語", "正業", "正命", "正精進", "正念", "正定"],
    "菩薩行": ["菩薩", "六度", "波羅蜜", "波羅密", "菩薩道"],
    "淨土": ["極樂", "西方淨土", "西方", "阿彌陀", "安樂世界"],
    "阿羅漢果": ["阿羅漢", "羅漢", "應供", "殺賊", "無生"],
    "阿羅漢": ["羅漢", "阿羅漢果", "應供", "殺賊"],
    "阿含": ["āgama", "agama", "法歸"],
    "戒律": ["律藏", "vinaya", "禁律", "戒法"],
    "律藏": ["vinaya", "戒律", "禁律"],
    "禪定": ["禪那", "三昧", "samādhi", "定", "坐禪"],
    "禪那": ["dhyāna", "三昧", "samādhi", "定", "禪定"],
    "無常": ["anitya", "impermanence"],
    "無我": ["anātman", "anatman", "非我"],
    "中道": ["madhyamā", "middle way", "八不中"],
    "如來": ["tathāgata", "tathagata", "佛"],
    "眾生": ["sattva", "有情"],
}

CANON_ALIASES: dict[str, str] = {
    "長阿含": "T01n0001",
    "長阿含經": "T01n0001",
    "阿含經": "T01n0001",
    "大品般若": "T02n0223",
    "般若波羅蜜": "T02n0223",
    "般若波羅蜜多": "T02n0223",
    "金剛經": "T08n0235",
    "金剛般若波羅蜜經": "T08n0235",
    "金剛般若波羅蜜": "T08n0235",
    "金剛般若": "T08n0235",
    "心經": "T08n0251",
    "般若心經": "T08n0251",
    "法華經": "T09n0262",
    "妙法蓮華": "T09n0262",
    "華嚴經": "T10n0279",
    "大方廣佛華嚴": "T10n0279",
    "阿彌陀經": "T12n0360",
    "無量壽經": "T12n0361",
    "觀無量壽經": "T12n0365",
    "摩訶僧祇律": "T24n1461",
    "楞嚴經": "T19n0945",
    "解深密經": "T16n0675",
    "維摩詰經": "T14n0475",
    "地藏經": "T13n0412",
    "壇經": "T48n2008",
}

_CANON_ID_RE = re.compile(r"\b([A-Z]{1,3}\d+n\d+[a-zA-Z]?)\b", re.I)
_SHORT_T_RE = re.compile(r"\bT(\d{2})n?(\d{3,4})\b", re.I)


@dataclass
class PreprocessedQuery:
    original: str
    normalized: str
    series_hint: str
    intent: str
    canon_ids: list[str]
    canon_prefixes: list[str]


def normalize_canon_prefix(raw: str) -> str | None:
    """Return ILIKE prefix e.g. T01N0001 from T01n0001 or T010001."""
    s = raw.strip().upper()
    m = _CANON_ID_RE.search(s)
    if m:
        return m.group(1).upper()
    m2 = _SHORT_T_RE.search(s)
    if m2:
        vol, num = m2.group(1), m2.group(2)
        return f"T{vol}N{num}"
    return None


def canon_prefixes_from_ids(canon_ids: list[str]) -> list[str]:
    out: list[str] = []
    for cid in canon_ids:
        p = normalize_canon_prefix(cid)
        if p and p not in out:
            out.append(p)
    return out


def _expand_terms(text: str) -> str:
    extra: list[str] = []
    for term, alts in TERM_MAP.items():
        if term in text:
            extra.extend(alts)
        for alt in alts:
            if alt.lower() in text.lower():
                extra.append(term)
    if extra:
        return text + " " + " ".join(sorted(set(extra)))
    return text


def _normalize_canon(text: str) -> tuple[str, list[str]]:
    """Resolve canon IDs from aliases; prefer longest non-overlapping spans."""
    matches: list[tuple[int, int, str, str]] = []
    for alias, cid in CANON_ALIASES.items():
        start = 0
        while True:
            idx = text.find(alias, start)
            if idx < 0:
                break
            matches.append((idx, idx + len(alias), alias, cid))
            start = idx + 1
    matches.sort(key=lambda m: (-len(m[2]), m[0]))
    used_spans: list[tuple[int, int]] = []
    ids: list[str] = []
    for start, end, _alias, cid in matches:
        if any(not (end <= s or start >= e) for s, e in used_spans):
            continue
        used_spans.append((start, end))
        if cid not in ids:
            ids.append(cid)
            text = text + f" {cid}"
    for m in _CANON_ID_RE.finditer(text):
        raw = m.group(1).upper()
        if raw not in ids:
            ids.append(raw)
    return text, list(dict.fromkeys(ids))


def detect_intent(text: str) -> str:
    if re.search(r"出處|哪部經|何經|經名", text):
        return "provenance"
    if re.search(r"原文|經文|怎麼說|如何記載", text):
        return "citation"
    return "doctrine"


def preprocess_query(query: str, *, default_series: str = "T") -> PreprocessedQuery:
    q = query.strip()
    q = _expand_terms(q)
    q, canon_ids = _normalize_canon(q)
    intent = detect_intent(q)
    prefixes = canon_prefixes_from_ids(canon_ids)
    series_hint = default_series
    if prefixes:
        series_hint = prefixes[0][0]
    elif canon_ids:
        series_hint = canon_ids[0][0]
    return PreprocessedQuery(
        original=query,
        normalized=q,
        series_hint=series_hint,
        intent=intent,
        canon_ids=canon_ids,
        canon_prefixes=prefixes,
    )
