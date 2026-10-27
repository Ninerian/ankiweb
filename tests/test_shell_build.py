import shutil
import subprocess
from pathlib import Path

import pytest


def test_shell_bundle_built():
    out = Path(__file__).resolve().parent.parent / "ankiweb/shell/static/bootstrap.js"
    assert out.exists(), "run: npm install && npm run build"
    assert b"WebSocket" in out.read_bytes()


def test_datastar_bundle_fetched():
    out = Path(__file__).resolve().parent.parent / "ankiweb/shell/static/datastar.js"
    assert out.exists(), "run: python tools/fetch_datastar.py"
    assert b"Datastar" in out.read_bytes()


@pytest.mark.parametrize(
    ("dev_script", "prod_script"),
    [("build:dev", "build"), ("build:css:dev", "build:css")],
)
def test_dev_css_is_isolated_and_removed_by_production_build(
    tmp_path: Path, dev_script: str, prod_script: str
) -> None:
    root = Path(__file__).resolve().parent.parent
    npm = shutil.which("npm")
    assert npm is not None, "npm is required for shell build tests"
    shutil.copytree(root / "shell_src", tmp_path / "shell_src")
    shutil.copytree(
        root / "ankiweb",
        tmp_path / "ankiweb",
        ignore=shutil.ignore_patterns(
            "static", "dev-static", "web_assets", "_import_tmp", "__pycache__", "*.pyc"
        ),
    )
    (tmp_path / "tools").mkdir()
    shutil.copy2(root / "tools/build_shell.mjs", tmp_path / "tools/build_shell.mjs")
    shutil.copy2(root / "package.json", tmp_path / "package.json")
    (tmp_path / "node_modules").symlink_to(
        root / "node_modules", target_is_directory=True
    )

    templates = tmp_path / "ankiweb/adapters/inbound/http_shared/templates"
    sources = {
        templates / "components/build_shared.html.jinja": 91830,
        templates / "component_gallery.html.jinja": 91831,
        templates / "components/_demo_badge.html.jinja": 91832,
        tmp_path / "ankiweb/adapters/inbound/http_shared/component_gallery.py": 91833,
        tmp_path / "ankiweb/adapters/inbound/http_datastar/dev_progress.py": 91834,
        tmp_path / "shell_src/dev/build_fixture.js": 91835,
        tmp_path / "docs/build_fixture.html": 91836,
        tmp_path / "tests/build_fixture.html": 91837,
        tmp_path / "ankiweb/web_assets/build_fixture.html": 91838,
        tmp_path / "ankiweb/shell/static/build_fixture.html": 91839,
        tmp_path / "ankiweb/shell/dev-static/build_fixture.html": 91840,
    }
    for path, number in sources.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as source:
            source.write(f"\nw-[{number}px]\n")

    subprocess.run([npm, "run", dev_script], cwd=tmp_path, check=True)
    static = tmp_path / "ankiweb/shell/static"
    dev_static = tmp_path / "ankiweb/shell/dev-static"
    common = {
        name: (static / name).read_bytes()
        for name in ("app.css", "theme.css", "components.css")
    }
    common_css = b"".join(common.values())
    gallery_css = (dev_static / "gallery.css").read_bytes()

    def selector(number: int) -> bytes:
        return rf".w-\[{number}px\]".encode()

    assert selector(91830) in common_css
    for number in range(91831, 91841):
        assert selector(number) not in common_css
    assert b".component-gallery" not in common_css
    assert b".component-gallery" in gallery_css
    assert b".radial-progress" in gallery_css
    for number in (91831, 91832, 91835):
        assert selector(number) in gallery_css
    for number in (91833, 91834, 91836, 91837, 91838, 91839, 91840):
        assert selector(number) not in gallery_css
    assert not (static / "dev-static").exists()

    subprocess.run([npm, "run", prod_script], cwd=tmp_path, check=True)
    assert not dev_static.exists()
    assert common == {name: (static / name).read_bytes() for name in common}
