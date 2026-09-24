from pathlib import Path
import pytest

ASSETS = Path(__file__).resolve().parent.parent / "ankiweb" / "web_assets"
SHELL_STATIC = Path(__file__).resolve().parent.parent / "ankiweb" / "shell" / "static"

pytestmark = pytest.mark.skipif(
    not ASSETS.exists(), reason="run tools/fetch_web_assets.py first"
)


def test_required_assets_vendored():
    for rel in [
        "js/reviewer.js",
        "css/reviewer.css",
        "sveltekit/index.html",
        "js/vendor/jquery.min.js",
        "VERSION",
    ]:
        assert (ASSETS / rel).exists(), f"missing {rel}"
    assert (ASSETS / "VERSION").read_text().strip() == "26.9.2"

def test_datastar_asset_vendored():
    datastar_js = SHELL_STATIC / "datastar.js"
    assert datastar_js.exists(), "missing datastar.js: run tools/fetch_datastar.py"
    assert "Datastar" in datastar_js.read_text(encoding="utf-8")
