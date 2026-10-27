import html
import re
from html.parser import HTMLParser

# Allowed HTML tags
ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "i",
        "u",
        "em",
        "strong",
        "br",
        "p",
        "div",
        "span",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "code",
        "pre",
        "blockquote",
        "img",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
    }
)

# Void tags (self-closing in HTML)
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# Tags whose content should be dropped completely when stripped
DROP_CONTENT_TAGS = frozenset(
    {"script", "style", "iframe", "noscript", "template", "object", "embed"}
)

# Allowed URL schemes for links and images
ALLOWED_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
ALLOWED_IMG_SCHEMES = frozenset({"http", "https"})


def _is_safe_url(url: str, allowed_schemes: frozenset[str]) -> bool:
    if not url:
        return False
    clean_url = url.strip()
    # Reject javascript:, vbscript:, data:, etc.
    if re.match(r"^\s*([a-zA-Z0-9+.-]+)\s*:", clean_url):
        scheme = clean_url.split(":", 1)[0].strip().lower()
        return scheme in allowed_schemes
    # If no scheme (relative URL like /foo or foo.png), allow
    return True


def _clean_attr(
    tag: str, name: str, val: str | None, cleaned_attrs: list[tuple[str, str]]
) -> bool:
    if val is None:
        return False
    name_lower = name.lower()
    val_str = str(val)

    # Never allow inline events or style or class
    if name_lower.startswith("on") or name_lower in ("style", "class"):
        return False

    if tag == "a" and name_lower == "href":
        if _is_safe_url(val_str, ALLOWED_LINK_SCHEMES):
            cleaned_attrs.append(("href", val_str))
            return True
    elif tag == "img" and name_lower == "src":
        if _is_safe_url(val_str, ALLOWED_IMG_SCHEMES):
            cleaned_attrs.append(("src", val_str))
    elif name_lower in ("title", "alt"):
        cleaned_attrs.append((name_lower, val_str))
    return False


def _clean_attrs(
    tag: str, attrs: list[tuple[str, str | None]]
) -> list[tuple[str, str]] | None:
    cleaned_attrs: list[tuple[str, str]] = []
    is_link = tag == "a"
    has_safe_href = False
    for name, val in attrs:
        if _clean_attr(tag, name, val, cleaned_attrs):
            has_safe_href = True

    if is_link and not has_safe_href:
        return None  # Disallowed link, do not emit <a> tag
    if is_link:
        cleaned_attrs.extend([("target", "_blank"), ("rel", "noopener noreferrer")])
    return cleaned_attrs


class _HTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.result: list[str] = []
        self.drop_stack: list[str] = []
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()
        if tag_lower in DROP_CONTENT_TAGS:
            self.drop_stack.append(tag_lower)
            return

        if self.drop_stack:
            return

        if tag_lower not in ALLOWED_TAGS:
            # Drop tag, keep content
            return

        cleaned_attrs = _clean_attrs(tag_lower, attrs)
        if cleaned_attrs is None:
            return

        if tag_lower not in VOID_TAGS:
            self.tag_stack.append(tag_lower)

        # Build start tag
        attr_str = "".join(
            f' {k}="{html.escape(v, quote=True)}"' for k, v in cleaned_attrs
        )
        self.result.append(f"<{tag_lower}{attr_str}>")

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if self.drop_stack:
            if self.drop_stack[-1] == tag_lower:
                self.drop_stack.pop()
            return

        if tag_lower not in ALLOWED_TAGS or tag_lower in VOID_TAGS:
            return
        if self.tag_stack and self.tag_stack[-1] == tag_lower:
            self.tag_stack.pop()
            self.result.append(f"</{tag_lower}>")
        elif tag_lower in self.tag_stack:
            while self.tag_stack:
                popped = self.tag_stack.pop()
                self.result.append(f"</{popped}>")
                if popped == tag_lower:
                    break

    def handle_data(self, data: str):
        if not self.drop_stack:
            self.result.append(data)

    def handle_entityref(self, name: str):
        if not self.drop_stack:
            self.result.append(f"&{name};")

    def handle_charref(self, name: str):
        if not self.drop_stack:
            self.result.append(f"&#{name};")

    def handle_comment(self, data: str):
        # Strip comments
        pass

    def close(self):
        super().close()
        while self.tag_stack:
            popped = self.tag_stack.pop()
            self.result.append(f"</{popped}>")


def sanitize_html(content: str) -> str:
    """Sanitize HTML string to allow only safe tags and attributes."""
    if not content:
        return ""
    parser = _HTMLSanitizer()
    parser.feed(content)
    parser.close()
    return "".join(parser.result)
