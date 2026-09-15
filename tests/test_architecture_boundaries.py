"""Architecture fitness test: ankiweb.core must never import ankiweb.adapters. This is the
automated enforcement of the hexagonal dependency rule from
docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md."""

from __future__ import annotations
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "ankiweb" / "core"


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_never_imports_adapters():
    violations = []
    for py_file in CORE.rglob("*.py"):
        for mod in _imported_top_level_modules(py_file):
            if mod.startswith("ankiweb.adapters") or mod == "ankiweb.adapters":
                violations.append(
                    f"{py_file.relative_to(CORE.parent.parent)} imports {mod}"
                )
    assert not violations, "core -> adapters import(s) found:\n" + "\n".join(violations)
