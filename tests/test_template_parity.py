"""The template is what ``pycompose init`` scaffolds, so it must carry the modules.

The package's copy of the scaffold is assembled from ``android/`` and the
template's own overlay (``tools/template/sync.py``), never committed. What can
still go wrong is the assembly's rules: an exclusion wide enough to drop a new
framework source would scaffold apps with a renderer from before the feature
it renders, surfacing as an unresolved reference in somebody's project.
"""

from __future__ import annotations

from pathlib import Path

from tools.template.sync import TEMPLATES, assemble, is_excluded, plan

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
MODULES = ("ir", "renderer", "host")


def test_every_framework_source_is_carried_by_the_template() -> None:
    """A module source the template lacks is a file generated apps never get."""
    carried = plan()[TEMPLATES / "android"]
    for module in MODULES:
        source_root = ANDROID / module / "src/main"
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or is_excluded(path.relative_to(source_root)):
                continue
            relative = path.relative_to(ANDROID)
            assert carried.get(relative) == path, (
                f"{relative} is not assembled into the template; "
                "`pycompose init` would scaffold a project without it"
            )


def test_assembly_removes_a_file_no_source_produces() -> None:
    stale = TEMPLATES / "android" / "renderer" / "Removed.kt"
    stale.write_text("// deleted from android/ since the last assembly\n")
    assemble()
    assert not stale.exists()


def test_assembly_is_complete() -> None:
    """Assembled once (the test session does), there is nothing left to change."""
    assert assemble(check=True) == []
