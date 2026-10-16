"""The closed vocabularies have exactly one home in the runtime registry."""

from __future__ import annotations

import re
from pathlib import Path

from pycompose.core.registry_types import CONSUMERS, SCOPE_PATHS, SCOPES, SLOT_KINDS

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "pycompose" / "core" / "registry_vocabulary.py"
TERMS = ("SLOT_KINDS", "CONSUMERS", "SCOPES", "SCOPE_PATHS")


def _hand_sources() -> list[Path]:
    """Return every hand-written Python file the vocabulary could leak into."""
    roots = [
        ROOT / "pycompose",
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
    including mirrors and generated copies.
    """
    for path in _hand_sources():
        if path == HOME:
            continue
        text = path.read_text()
        for term in TERMS:
            assert not re.search(
                rf"^{term} = ", text, re.MULTILINE
            ), f"{path} redefines {term}; import it from registry_vocabulary"


def test_scope_paths_pair_with_the_closed_scope_tuple() -> None:
    """The path table covers the scope tuple exactly; neither grows alone."""
    assert set(SCOPE_PATHS) == set(SCOPES)
    assert SLOT_KINDS and CONSUMERS
