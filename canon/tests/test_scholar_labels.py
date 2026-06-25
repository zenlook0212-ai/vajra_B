"""Tests for scholar canon labels."""

from canon.query.extractive_synth import scholar_canon_label


def test_scholar_canon_label_known():
    assert scholar_canon_label("T02n0099") == "雜阿含 T99"
    assert scholar_canon_label("T01n0001") == "長阿含 T1"


def test_scholar_canon_label_vol_fallback():
    assert scholar_canon_label("T30n1579") == "論藏 T1579"
