import html
import re
from html.parser import HTMLParser

# Allowed HTML tags
ALLOWED_TAGS = frozenset({
    "a", "b", "i", "u", "em", "strong", "br", "p", "div", "span",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "code", "pre", "blockquote", "img",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
})

# Void tags (self-closing in HTML)
VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

# Tags whose content should be dropped completely when stripped
DROP_CONTENT_TAGS = frozenset({"script", "style", "iframe", "noscript", "template", "object", "embed"})

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

        # Sanitize attributes
        cleaned_attrs: list[tuple[str, str]] = []
        is_link = tag_lower == "a"
        is_img = tag_lower == "img"
        has_safe_href = False

        for name, val in attrs:
            if val is None:
                continue
            name_lower = name.lower()
            val_str = str(val)

            # Never allow inline events or style or class
            if name_lower.startswith("on") or name_lower in ("style", "class"):
                continue

            if is_link and name_lower == "href":
                if _is_safe_url(val_str, ALLOWED_LINK_SCHEMES):
                    cleaned_attrs.append(("href", val_str))
                    has_safe_href = True
            elif is_img and name_lower == "src":
                if _is_safe_url(val_str, ALLOWED_IMG_SCHEMES):
                    cleaned_attrs.append(("src", val_str))
            elif name_lower in ("title", "alt"):
                cleaned_attrs.append((name_lower, val_str))

        if is_link and not has_safe_href:
            # Disallowed link (e.g. javascript:), do not emit <a> tag
            return

        if is_link:
            cleaned_attrs.append(("target", "_blank"))
            cleaned_attrs.append(("rel", "noopener noreferrer"))

        if tag_lower not in VOID_TAGS:
            self.tag_stack.append(tag_lower)

        # Build start tag
        attr_str = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in cleaned_attrs)
        self.result.append(f"<{tag_lower}{attr_str}>")

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if self.drop_stack:
            if self.drop_stack[-1] == tag_lower:
                self.drop_stack.pop()
            return

        if tag_lower in ALLOWED_TAGS and tag_lower not in VOID_TAGS:
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
