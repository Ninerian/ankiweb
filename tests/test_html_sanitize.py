from html.parser import HTMLParser

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
    assert (
        sanitized
        == "<p>Paragraph with <b>bold</b>, <i>italic</i>, and <code>code</code>.</p>"
    )


class _RenderedContent(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


@pytest.mark.parametrize(
    ("tag", "visible_entity"),
    [
        ("xmp", "&amp;"),
        ("noembed", "&amp;"),
        ("noframes", "&amp;"),
        ("title", "&"),
        ("textarea", "&"),
    ],
)
@pytest.mark.parametrize("opening_suffix", [">", "/>"])
def test_sanitize_text_only_elements_do_not_create_markup(
    tag, visible_entity, opening_suffix
):
    payload = '<img src=x onerror="window.reviewXss=1">'
    raw = (
        f"<b>safe &amp; sound</b><{tag}{opening_suffix}"
        f"before {payload} &amp; after</{tag}><i>end</i>"
    )
    rendered = _RenderedContent()
    rendered.feed(sanitize_html(raw))
    rendered.close()

    assert rendered.tags == ["b", "i"]
    assert "".join(rendered.text) == (
        f"safe & soundbefore {payload} {visible_entity} afterend"
    )


@pytest.mark.parametrize("tag", ["xmp", "noembed", "noframes", "title", "textarea"])
def test_sanitize_unclosed_text_only_element_keeps_payload_inert(tag):
    payload = '<img src=x onerror="window.reviewXss=1">'
    rendered = _RenderedContent()
    rendered.feed(sanitize_html(f"<{tag}>{payload}"))
    rendered.close()

    assert rendered.tags == []
    assert "".join(rendered.text) == payload


@pytest.mark.parametrize("opening", ["<plaintext>", "<plaintext/>"])
def test_sanitize_plaintext_consumes_the_remainder_as_text(opening):
    payload = '<img src=x onerror="window.reviewXss=1">'
    remainder = f"{payload} &amp; </plaintext><b>still text</b>"
    rendered = _RenderedContent()
    rendered.feed(sanitize_html(f"<i>before</i>{opening}{remainder}"))
    rendered.close()

    assert rendered.tags == ["i"]
    assert "".join(rendered.text) == f"before{remainder}"


def test_sanitize_preserves_entities_and_escapes_text():
    raw = "<p>A &amp; B &#60; C &gt; D & E</p><textarea>&lt;b&gt;&amp;&#65;</textarea>"
    rendered = _RenderedContent()
    rendered.feed(sanitize_html(raw))
    rendered.close()

    assert rendered.tags == ["p"]
    assert "".join(rendered.text) == "A & B < C > D & E<b>&A"
