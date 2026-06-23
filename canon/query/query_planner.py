"""Query type classification and dynamic retrieval parameters (Phase A)."""

from __future__ import annotations

from dataclasses import dataclass

from canon.query.preprocess import PreprocessedQuery

# Doctrine term -> preferred canon volume prefixes for soft RRF boost (D-class).
DOCTRINE_CANON_BOOST: dict[str, list[str]] = {
    "緣起": ["T01", "T02"],
    "因緣": ["T01", "T02"],
    "十二因緣": ["T01", "T02"],
    "十二緣起": ["T01", "T02"],
    "四諦": ["T01", "T02"],
    "八正道": ["T01", "T02"],
    "無常": ["T01", "T02"],
    "無我": ["T01", "T02", "T08"],
    "涅槃": ["T01", "T02", "T09"],
    "般若": ["T06", "T08", "T02"],
    "空性": ["T06", "T08", "T02"],
    "菩提心": ["T09", "T10", "T14", "T02"],
    "菩提": ["T09", "T10", "T14", "T02", "T08"],
    "菩薩行": ["T09", "T10", "T14"],
    "菩薩": ["T09", "T10", "T14"],
    "淨土": ["T12", "T36", "T09", "T10"],
    "阿彌陀": ["T12", "T36"],
    "戒律": ["T23", "T24", "T01", "T02"],
    "律藏": ["T23", "T24", "T01", "T02"],
    "阿羅漢果": ["T01", "T02"],
    "阿羅漢": ["T01", "T02"],
    "禪定": ["T01", "T02", "T48", "T15"],
    "禪那": ["T01", "T02", "T48", "T15"],
    "中道": ["T01", "T02", "T08", "T09"],
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
