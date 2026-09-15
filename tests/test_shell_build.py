from pathlib import Path


def test_shell_bundle_built():
    out = Path(__file__).resolve().parent.parent / "ankiweb/shell/static/bootstrap.js"
    assert out.exists(), "run: npm install && npm run build"
    assert b"WebSocket" in out.read_bytes()


def test_shell_bundle_has_nav_helpers():
    out = Path(__file__).resolve().parent.parent / "ankiweb/shell/static/bootstrap.js"
    data = out.read_bytes()
    assert b"ankiwebNavigate" in data
    assert b"anki-opchanges" in data


def test_bootstrap_has_opchanges_optout():
    from pathlib import Path

    js = Path("ankiweb/shell/static/bootstrap.js").read_text()
    assert "__ankiwebOnOpchanges" in js


def test_datastar_bundle_fetched():
    out = Path(__file__).resolve().parent.parent / "ankiweb/shell/static/datastar.js"
    assert out.exists(), "run: python tools/fetch_datastar.py"
    assert b"Datastar" in out.read_bytes()
