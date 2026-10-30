"""The closed vocabularies have exactly one home in the runtime registry."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
PACKAGE = ROOT / "packages/pycompose/src/pycompose"
HOME = PACKAGE / "model" / "catalog" / "vocabulary.py"


def _terms() -> list[str]:
    """Read the home module's own constant names, so growth widens the scan.

    Returns:
        Every module-level ALL_CAPS assignment the home defines.
    """
    tree = ast.parse(HOME.read_text(encoding="utf-8"))
    names = [
        target.id
        for node in tree.body
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign) and node.value is not None
            else []
        )
        if isinstance(target, ast.Name) and target.id.isupper()
    ]
    assert names, "the home module must define its vocabularies"
    return names


def _hand_sources() -> list[Path]:
    """Return every hand-written Python file the vocabulary could leak into."""
    roots = [
        PACKAGE,
        ROOT / "tools",
        ROOT / "tests",
    ]
    found = [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert found, "the scan must actually see source files"
    return found


def test_the_closed_vocabularies_are_defined_in_one_module() -> None:
    """Names the renderer, codegen, and the pin audit share live in one place.

    A second definition is how a scope appears wired in one layer and unknown
    in another, so this scan refuses any assignment outside the home module,
    including mirrors and generated copies. The term list is the home's own
    assignments: a vocabulary added to the home is guarded from its first day.
    """
    terms = _terms()
    for path in _hand_sources():
        if path == HOME:
            continue
        text = path.read_text()
        for term in terms:
            assert not re.search(
                rf"^{term}\s*(?::[^=\n]*)?=", text, re.MULTILINE
            ), f"{path} redefines {term}; import it from vocabulary"
