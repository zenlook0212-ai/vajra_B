"""Query type classification and dynamic retrieval parameters (Phase A)."""

from __future__ import annotations

from dataclasses import dataclass

from canon.query.preprocess import PreprocessedQuery

# Doctrine term -> preferred canon volume prefixes for soft RRF boost (D-class).
# Longer prefixes (T02N0099) rank before series (T02) for volume-level steering.
DOCTRINE_CANON_BOOST: dict[str, list[str]] = {
    "緣起": ["T01N0001", "T02N0099", "T02N0125", "T02N0150", "T01", "T02"],
    "因緣": ["T01N0001", "T02N0099", "T02N0125", "T01", "T02"],
    "十二因緣": ["T01N0001", "T02N0099", "T02N0125", "T02N0150", "T01", "T02"],
    "十二緣起": ["T01N0001", "T02N0099", "T02N0125", "T02N0150", "T01", "T02"],
    "四諦": ["T02N0099", "T02N0125", "T01N0001", "T01", "T02"],
    "八正道": ["T02N0099", "T02N0125", "T01N0001", "T01", "T02"],
    "無常": ["T01N0001", "T02N0099", "T02N0125", "T01", "T02"],
    "無我": ["T01N0001", "T02N0099", "T08N0235", "T01", "T02", "T08"],
    "涅槃": ["T01N0001", "T02N0099", "T02N0125", "T09N0262", "T01", "T02", "T09"],
    "般若": ["T08N0235", "T08N0251", "T08N0223", "T06N0220", "T08", "T06"],
    "空性": ["T08N0235", "T08N0251", "T08N0221", "T08N0223", "T16N0675", "T08", "T16"],
    "菩提心": ["T09N0262", "T10N0279", "T14N0475", "T08N0223", "T09", "T10", "T14", "T08"],
    "菩提": ["T09N0262", "T10N0279", "T14N0475", "T08N0235", "T09", "T10", "T14", "T02", "T08"],
    "菩薩行": ["T09N0262", "T10N0279", "T14N0475", "T09", "T10", "T14"],
    "菩薩": ["T09N0262", "T10N0279", "T14N0475", "T09", "T10", "T14"],
    "淨土": ["T12N0360", "T12N0366", "T12N0365", "T09N0262", "T10N0279", "T12", "T09", "T10"],
    "阿彌陀": ["T12N0366", "T12N0360", "T12N0365", "T36N0279", "T12", "T36"],
    "戒律": ["T01N0001", "T02N0147", "T24N1461", "T01", "T02", "T24"],
    "律藏": ["T01N0001", "T02N0147", "T24N1461", "T01", "T02", "T24"],
    "阿羅漢果": ["T01N0001", "T02N0099", "T02N0125", "T01", "T02"],
    "阿羅漢": ["T01N0001", "T02N0099", "T02N0125", "T01", "T02"],
    "禪定": ["T01N0001", "T02N0099", "T48N2008", "T01", "T02", "T48", "T15"],
    "禪那": ["T01N0001", "T02N0099", "T48N2008", "T01", "T02", "T48", "T15"],
    "中道": ["T01N0001", "T08N0235", "T09N0262", "T08N0223", "T01", "T08", "T09"],
}

DEFAULT_VEC_TOP = 20
DEFAULT_BM25_TOP = 20
DEFAULT_FUSE_TOP = 30
DEFAULT_RERANK_TOP = 5

D_VEC_TOP = 40
D_BM25_TOP = 40
D_FUSE_TOP = 50
D_RERANK_TOP = 10
D_SUB_TERM_BM25_TOP = 10


@dataclass
class QueryPlan:
    query_type: str  # "A" | "C" | "D"
    vec_top: int
    bm25_top: int
    fuse_top: int
    rerank_top: int
    use_rule_expand: bool
    doctrine_boost_prefixes: list[str]
    sub_term_bm25_top: int = D_SUB_TERM_BM25_TOP


def _doctrine_boost_prefixes(query: str) -> list[str]:
    """Match longest doctrine keys first so 菩提心 wins over 菩提."""
    out: list[str] = []
    for term in sorted(DOCTRINE_CANON_BOOST.keys(), key=len, reverse=True):
        if term not in query:
            continue
        for p in DOCTRINE_CANON_BOOST[term]:
            if p not in out:
                out.append(p)
    return out


def classify_query(pq: PreprocessedQuery) -> QueryPlan:
    """Classify query and return retrieval plan.

    - canon_prefixes with one entry -> A (scoped single sutra)
    - canon_prefixes with multiple   -> C (multi-sutra scope)
    - no canon_prefixes              -> D (open doctrine)
    """
    prefixes = pq.canon_prefixes
    if prefixes:
        qtype = "A" if len(prefixes) == 1 else "C"
        return QueryPlan(
            query_type=qtype,
            vec_top=DEFAULT_VEC_TOP,
            bm25_top=DEFAULT_BM25_TOP,
            fuse_top=DEFAULT_FUSE_TOP,
            rerank_top=DEFAULT_RERANK_TOP,
            use_rule_expand=False,
            doctrine_boost_prefixes=[],
        )

    return QueryPlan(
        query_type="D",
        vec_top=D_VEC_TOP,
        bm25_top=D_BM25_TOP,
        fuse_top=D_FUSE_TOP,
        rerank_top=D_RERANK_TOP,
        use_rule_expand=True,
        doctrine_boost_prefixes=_doctrine_boost_prefixes(pq.original),
        sub_term_bm25_top=D_SUB_TERM_BM25_TOP,
    )
