"""Tests for per-app codegen (ADR-0014).

The property worth protecting is not "the slice is small". It is that the app's
Python slice and its Kotlin slice contain *the same* components. If they drift
apart the app can emit a node the host has no adapter for, and that surfaces as a
blank screen on a device rather than as an error on a build machine.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOTES_APP = ROOT / "examples/notes/app"
CATALOG = json.loads((ROOT / "schema/components.json").read_text())
GEN = ROOT / "tools/schema/gen.py"


def run_app(app: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Invoke gen.py in its --app mode.

    Args:
        app: The app directory.
        *extra: Further flags.

    Returns:
        The completed process.
    """
    return subprocess.run(
        [sys.executable, str(GEN), "--app", str(app), *extra],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


@pytest.fixture(scope="module")
def slice_names() -> set[str]:
    """Return the component names in the notes app's Kotlin slice.

    Returns:
        Every data class emitted as a component node.
    """
    models = (
        NOTES_APP / "android/ir/src/main/kotlin/com/pycompose/ir/generated/UiModels.kt"
    )
    if not models.exists():
        run_app(NOTES_APP)
    return set(re.findall(r"data class (\w+)Props\(", models.read_text()))


# ---------------------------------------------------------------------------
# The slice is what the app uses
# ---------------------------------------------------------------------------


def test_the_slice_holds_exactly_the_components_the_app_references(
    slice_names: set[str],
) -> None:
    """Discovery is by AST name, so the slice follows the source."""
    from pycompose.schema.codegen.app_slice import discover, load_catalog

    referenced = discover(NOTES_APP, load_catalog(ROOT / "schema/components.json"))
    assert slice_names == referenced
    assert len(slice_names) < len(
        CATALOG["components"]
    ), "the example no longer demonstrates anything if it uses everything"


def test_an_unused_component_is_absent_from_both_slices(slice_names: set[str]) -> None:
    """Checkbox is in the catalog and in neither the app's Python nor its Kotlin."""
    unused = set(CATALOG["components"]) - slice_names
    assert unused, "expected the example to leave something out"

    python_slice = (NOTES_APP / "m3/generated_components.py").read_text()
    contract = (
        NOTES_APP
        / "android/ir/src/main/kotlin/com/pycompose/ir/generated/IrContract.kt"
    ).read_text()
    for name in unused:
        assert f"class {name}(" not in python_slice, f"{name} leaked into Python"
        assert f'"{name}"' not in contract, f"{name} leaked into the IR contract"


def test_the_two_slices_agree(slice_names: set[str]) -> None:
    """A component in one slice but not the other is a blank screen waiting.

    Nothing structurally prevents this: they are rendered by different functions
    into different languages from the same input. The test is the guarantee.
    """
    python_slice = (NOTES_APP / "m3/generated_components.py").read_text()
    python_names = set(re.findall(r"^class (\w+)\(", python_slice, re.MULTILINE))
    assert python_names == slice_names


# ---------------------------------------------------------------------------
# Discovery actually works
# ---------------------------------------------------------------------------


def test_an_imported_component_counts_even_if_never_used(tmp_path: Path) -> None:
    """`from m3 import Button` binds an alias, not a Name.

    Scanning names alone finds a component only where it is *used*, so an app
    that imports one to re-export it would silently drop it -- and the build
    would fail on an import that looks perfectly ordinary.
    """
    from pycompose.schema.codegen.app_slice import discover, load_catalog

    app = tmp_path / "app"
    app.mkdir()
    (app / "screen.py").write_text("from m3 import Button\n\nX = 1\n")
    used = discover(app, load_catalog(ROOT / "schema/components.json"))
    assert used == {"Button"}


def test_the_generated_package_does_not_discover_itself(tmp_path: Path) -> None:
    """Otherwise the slice feeds itself and grows without an app asking."""
    from pycompose.schema.codegen.app_slice import discover, load_catalog

    app = tmp_path / "app"
    (app / "m3").mkdir(parents=True)
    (app / "m3/generated_components.py").write_text("class Everything: pass\n")
    (app / "screen.py").write_text("X = 1\n")
    catalog = load_catalog(ROOT / "schema/components.json")
    assert discover(app, catalog) == set()


def test_usage_as_an_attribute_counts(tmp_path: Path) -> None:
    """`m3.Button` is an Attribute, not a Name."""
    from pycompose.schema.codegen.app_slice import discover, load_catalog

    app = tmp_path / "app"
    app.mkdir()
    (app / "screen.py").write_text("import m3\n\nnode = m3.Spacer\n")
    assert discover(app, load_catalog(ROOT / "schema/components.json")) == {"Spacer"}


def test_an_app_with_no_components_is_an_error(tmp_path: Path) -> None:
    """Silently generating nothing would ship a host that renders nothing."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "screen.py").write_text("X = 1\n")
    result = run_app(app)
    assert result.returncode != 0
    assert "no components" in result.stderr


def test_a_missing_directory_is_an_error(tmp_path: Path) -> None:
    """A typo in a build script should fail, not create a tree."""
    result = run_app(tmp_path / "nope")
    assert result.returncode != 0
    assert "not a directory" in result.stderr


# ---------------------------------------------------------------------------
# --check is a real gate
# ---------------------------------------------------------------------------


def test_check_passes_on_a_fresh_slice() -> None:
    """Generated output is build artifact, but --check is still how CI sees it."""
    run_app(NOTES_APP)
    result = run_app(NOTES_APP, "--check")
    assert result.returncode == 0, result.stderr


def test_check_fails_when_the_slice_is_wrong() -> None:
    """Drift is detectable, which is what makes the slice safe to ship."""
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        app = Path(raw) / "app"
        shutil_copy(NOTES_APP, app)
        run_app(app)
        models = (
            app / "android/ir/src/main/kotlin/com/pycompose/ir/generated/UiModels.kt"
        )
        models.write_text(models.read_text().replace("Spacer", "SpacerX"))
        result = run_app(app, "--check")
        assert result.returncode == 1
        assert "drift" in result.stderr


def shutil_copy(source: Path, destination: Path) -> None:
    """Copy a directory tree without importing shutil at module scope.

    Args:
        source: The tree to copy.
        destination: Where to put it.
    """
    import shutil

    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("android"))
