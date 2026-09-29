"""Download the Bootstrap 5 framework bundle into ankiweb/shell/static/vendor/."""
from __future__ import annotations
import urllib.request
from pathlib import Path

BOOTSTRAP_VERSION = "5.3.3"
DEST = Path(__file__).resolve().parent.parent / "ankiweb" / "shell" / "static" / "vendor"
CSS_URL = f"https://cdn.jsdelivr.net/npm/bootstrap@{BOOTSTRAP_VERSION}/dist/css/bootstrap.min.css"
JS_URL = f"https://cdn.jsdelivr.net/npm/bootstrap@{BOOTSTRAP_VERSION}/dist/js/bootstrap.bundle.min.js"


def _fetch(url: str, marker: bytes) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ankiweb-fetcher"})
    with urllib.request.urlopen(req) as resp:
        content = resp.read()
    if not content or marker not in content:
        raise SystemExit(f"downloaded {url} is empty or missing expected marker")
    return content


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    css = _fetch(CSS_URL, b"Bootstrap")
    (DEST / "bootstrap.min.css").write_bytes(css)
    js = _fetch(JS_URL, b"bootstrap")
    (DEST / "bootstrap.bundle.min.js").write_bytes(js)
    (DEST / "BOOTSTRAP_VERSION").write_text(BOOTSTRAP_VERSION + "\n")
    print(f"vendored bootstrap {BOOTSTRAP_VERSION} -> {DEST} (css {len(css)}B, js {len(js)}B)")


if __name__ == "__main__":
    main()
