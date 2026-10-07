"""Deterministically seed a fresh ankiweb collection for the autoresearch UX-navigation
harness, by importing a local .apkg via the anki pylib (the same backend call ankiweb's
own /import route uses — see ankiweb/core/ankiconnect_actions/actions/import_export.py).

Usage: uv run python tools/harness_seed.py <apkg_path> <dest_collection_path>

Produces a collection with real decks/notes/notetypes so the crawler has substantive
screens (Browse, Stats, Notetypes, deck options, ...) to traverse, instead of an empty
"Default" deck. Deterministic: same input .apkg -> same resulting collection contents
every run (no network, no clock-dependent behavior affects navigation structure).
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "usage: harness_seed.py <apkg_path> <dest_collection_path>", file=sys.stderr
        )
        raise SystemExit(2)

    apkg_path = Path(sys.argv[1]).expanduser().resolve()
    dest_path = Path(sys.argv[2]).expanduser()

    if not apkg_path.is_file():
        print(f"apkg not found: {apkg_path}", file=sys.stderr)
        raise SystemExit(2)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()

    import anki.import_export_pb2 as ie
    from anki.collection import Collection

    col = Collection(str(dest_path))
    try:
        resp = col.import_anki_package(
            ie.ImportAnkiPackageRequest(package_path=str(apkg_path))
        )
        found = getattr(resp.log, "found_notes", None) if resp.HasField("log") else None
        print(f"seeded {dest_path} from {apkg_path.name} (found_notes={found})")
    finally:
        col.close()


if __name__ == "__main__":
    main()
