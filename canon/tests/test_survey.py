"""Tests for canon survey (B1)."""

from canon.query.survey import expand_survey_terms, format_survey_markdown


def test_expand_survey_terms_includes_synonyms():
    terms = expand_survey_terms("佛經中如何說十二因緣")
    assert "十二因緣" in terms
    assert "緣起" in terms or "因緣" in terms


def test_format_survey_markdown_empty():
    md = format_survey_markdown(
        {"query": "無此詞", "terms_searched": ["無此詞"], "groups": [], "total_hits": 0, "canon_count": 0},
        cbeta_url_fn=lambda cid: f"https://example/{cid}",
    )
    assert "全藏出處" in md
    assert "未找到" in md


def test_format_survey_markdown_with_group():
    md = format_survey_markdown(
        {
            "query": "四諦",
            "terms_searched": ["四諦"],
            "total_hits": 3,
            "canon_count": 1,
            "groups": [
                {
                    "canon_id": "T02n0099",
                    "hit_count": 3,
                    "samples": [{"coord": "【T02n0099_p0123a01】", "excerpt": "苦諦"}],
                }
            ],
        },
        cbeta_url_fn=lambda cid: f"https://cbeta/{cid}",
    )
    assert "T02n0099" in md
    assert "https://cbeta/T02n0099" in md
