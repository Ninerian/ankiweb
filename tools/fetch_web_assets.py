"""Download the aqt wheel (no deps) via uv and extract _aqt/data/web/ into ankiweb/web_assets/."""

from __future__ import annotations
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

AQT_VERSION = "26.9.2"
DEST = Path(__file__).resolve().parent.parent / "ankiweb" / "web_assets"
REQUIRED = [
    "js/reviewer.js",
    "js/reviewer-bottom.js",
    "css/reviewer.css",
    "sveltekit/index.html",
    "pages/congrats.html",
    "js/vendor/jquery.min.js",
]


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        uv_bin = shutil.which("uv") or "uv"
        subprocess.run(
            [
                uv_bin,
                "pip",
                "install",
                f"aqt=={AQT_VERSION}",
                "--no-deps",
                "--target",
                str(td),
                "--python",
                sys.executable,
            ],
            check=True,
        )
        src_dir = td / "_aqt" / "data" / "web"
        if not src_dir.exists():
            raise SystemExit(
                "aqt installation has no _aqt/data/web/ — version layout changed"
            )
        if DEST.exists():
            shutil.rmtree(DEST)
        shutil.copytree(src_dir, DEST)
    missing = [r for r in REQUIRED if not (DEST / r).exists()]
    if missing:
        raise SystemExit(f"missing required assets: {missing}")
    (DEST / "VERSION").write_text(AQT_VERSION + "\n")
    print(f"vendored aqt {AQT_VERSION} assets -> {DEST}")


if __name__ == "__main__":
    main()
