import pytest
from ankiweb.core.html_sanitize import sanitize_html


def test_sanitize_preserves_allowed_links_with_rel_and_target():
    raw = 'Please see the <a href="https://ankiweb.net/shared/info/3180012916">shared deck page</a> for more info.'
    sanitized = sanitize_html(raw)
    assert 'href="https://ankiweb.net/shared/info/3180012916"' in sanitized
    assert 'target="_blank"' in sanitized
    assert 'rel="noopener noreferrer"' in sanitized
    assert "shared deck page" in sanitized


def test_sanitize_strips_script_tag_and_content():
    raw = 'Before <script type="text/javascript">alert("xss")</script> After'
    sanitized = sanitize_html(raw)
    assert "<script" not in sanitized
    assert "alert" not in sanitized
    assert "Before  After" in sanitized


def test_sanitize_strips_onerror_attribute():
    raw = '<img src="https://example.com/pic.png" onerror="alert(1)" alt="photo">'
    sanitized = sanitize_html(raw)
    assert 'src="https://example.com/pic.png"' in sanitized
    assert "onerror" not in sanitized
    assert "alert" not in sanitized
    assert 'alt="photo"' in sanitized


def test_sanitize_strips_javascript_href():
    raw = '<a href="javascript:alert(1)">malicious link</a>'
    sanitized = sanitize_html(raw)
    assert "javascript:" not in sanitized
    assert "<a" not in sanitized
    assert "malicious link" in sanitized


def test_sanitize_plain_text_unchanged():
    raw = "This is a plain description with no HTML tags."
    sanitized = sanitize_html(raw)
    assert sanitized == raw


def test_sanitize_allowed_formatting_tags():
    raw = "<p>Paragraph with <b>bold</b>, <i>italic</i>, and <code>code</code>.</p>"
    sanitized = sanitize_html(raw)
    assert sanitized == "<p>Paragraph with <b>bold</b>, <i>italic</i>, and <code>code</code>.</p>"
