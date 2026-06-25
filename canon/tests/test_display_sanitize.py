"""Tests for display markdown sanitizer."""

from canon.query.display_sanitize import sanitize_display_markdown


def test_strips_bold_paragraph():
    raw = "第一段。\n\n**不同譯本在名相上略有差異，如「更樂」即觸。**"
    out = sanitize_display_markdown(raw)
    assert "**" not in out
    assert "不同譯本" in out


def test_strips_hr_and_heading():
    raw = "## 標題\n\n---\n\n正文"
    out = sanitize_display_markdown(raw)
    assert "---" not in out
    assert "標題" in out
    assert "正文" in out
