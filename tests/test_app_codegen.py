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


# ---------------------------------------------------------------------------
# The packaged catalog, for an app with no repository
# ---------------------------------------------------------------------------


def test_the_catalog_ships_in_the_package() -> None:
    """An installed wheel has no repo above it, so it must carry a catalog.

    Without this, `build_app` works in a checkout and fails for every real user,
    which is the shape of bug that only shows up after release.
    """
    from pycompose.schema.codegen import main as codegen

    assert (
        codegen.PACKAGED_CATALOG.is_file()
    ), "components.json is not shipped; an installed pycompose cannot generate"


def test_the_packaged_catalog_matches_the_source() -> None:
    """It is a generated artifact, so this should be unreachable.

    Asserted anyway because a duplicate of the SSOT is exactly what ADR-0002
    exists to prevent, and a copy that silently goes stale is worse than no
    copy at all -- apps would generate from a catalog the library has moved on
    from.
    """
    from pycompose.schema.codegen import main as codegen

    assert (
        codegen.PACKAGED_CATALOG.read_bytes()
        == (ROOT / "schema/components.json").read_bytes()
    )


def test_codegen_reads_the_packaged_catalog_when_there_is_no_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback path itself, not just the file's existence."""
    from pycompose.schema.codegen import main as codegen

    monkeypatch.setattr(codegen, "SCHEMA_PATH", codegen.PACKAGED_CATALOG)
    registry = codegen.load_registry()
    assert "Button" in registry["components"]


def test_the_library_codegen_runs_from_the_package() -> None:
    """`python -m pycompose.schema.codegen` is the entry point an app would use."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "pycompose.schema.codegen", "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Bound to the build (ADR-0014)
# ---------------------------------------------------------------------------


def test_an_app_on_the_library_catalog_is_left_alone(tmp_path: Path) -> None:
    """Binding codegen must not break apps that never adopted it."""
    from pycompose.schema.codegen.app_slice import uses_generated_slice

    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("from pycompose.m3 import Button\n")
    assert uses_generated_slice(app) is False


def test_an_app_that_adopted_the_slice_is_detected(tmp_path: Path) -> None:
    from pycompose.schema.codegen.app_slice import uses_generated_slice

    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("from m3 import Button\n")
    assert uses_generated_slice(app) is True


def test_adoption_ignores_the_generated_package_itself(tmp_path: Path) -> None:
    """Otherwise the slice makes itself look adopted forever."""
    from pycompose.schema.codegen.app_slice import uses_generated_slice

    app = tmp_path / "app"
    (app / "m3").mkdir(parents=True)
    (app / "m3" / "__init__.py").write_text(
        "from m3.generated_components import (\n    Button,\n)\n"
    )
    assert uses_generated_slice(app) is False


def test_the_two_roots_are_separate(tmp_path: Path) -> None:
    """A scaffolded project keeps Python under app/ and Android at the root.

    This is the layout `pycompose init` produces, and the reason `build_app`
    takes two roots: one directory holding both only ever worked for the notes
    example, which is how the conflation survived being wrong.
    """
    from pycompose.schema.codegen.main import build_app

    root = tmp_path / "project"
    python_root = root / "app"
    android_root = root
    (python_root / "screen").mkdir(parents=True)
    (android_root / "android/ir/src/main/kotlin/com/pycompose/ir/generated").mkdir(
        parents=True
    )
    (android_root / "android/host/src/main/kotlin/com/pycompose/host/ui").mkdir(
        parents=True
    )
    (python_root / "screen" / "view.py").write_text(
        "from m3 import Button, Spacer, Text\n"
    )

    assert build_app(python_root, android_root=android_root) == 0

    assert (python_root / "m3" / "generated_components.py").is_file()
    assert (
        android_root
        / "android/ir/src/main/kotlin/com/pycompose/ir/generated/UiModels.kt"
    ).is_file()
    # And nothing was written into the Android root's Python side.
    assert not (android_root / "m3").exists()


def test_the_python_root_still_works_alone(tmp_path: Path) -> None:
    """The notes example's layout, where both roots are one directory."""
    from pycompose.schema.codegen.main import build_app

    root = tmp_path / "app"
    root.mkdir()
    (root / "view.py").write_text("from m3 import Button\n")
    assert build_app(root) == 0
    assert (root / "m3" / "generated_components.py").is_file()
