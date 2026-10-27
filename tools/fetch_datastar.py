"""Download the Datastar frontend bundle into ankiweb/shell/static/datastar.js."""

from __future__ import annotations

from pathlib import Path

import httpx

DATASTAR_VERSION = "1.0.4"
DEST = Path(__file__).resolve().parent.parent / "ankiweb" / "shell" / "static"
BUNDLE_URL = f"https://raw.githubusercontent.com/starfederation/datastar/v{DATASTAR_VERSION}/bundles/datastar.js"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    out_file = DEST / "datastar.js"
    response = httpx.get(
        BUNDLE_URL,
        headers={"User-Agent": "ankiweb-fetcher"},
        follow_redirects=True,
        timeout=30.0,
    )
    response.raise_for_status()
    content = response.content
    if not content or b"Datastar" not in content:
        raise SystemExit(
            "downloaded Datastar bundle is empty or does not contain 'Datastar'"
        )
    out_file.write_bytes(content)
    (DEST / "DATASTAR_VERSION").write_text(DATASTAR_VERSION + "\n")
    print(
        f"vendored datastar {DATASTAR_VERSION} bundle -> {out_file} ({len(content)} bytes)"
    )


if __name__ == "__main__":
    main()
