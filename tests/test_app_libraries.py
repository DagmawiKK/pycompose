"""An app's own Compose libraries (plan 31 §16.3): closure, lock slice, runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pycompose.cli import add
from pycompose.cli.project import Project, ProjectError
from pycompose.compiler.app import ORIGIN, AppLibraryError, layered_closure
from pycompose.core.registry_types import ComponentRegistryError, Registry
from pycompose.ir.generated_validators import REGISTRY
from pycompose.schema.codegen.app_slice import app_components, with_app_lock
from pycompose.schema.codegen.emit_python import render_python_components

DEFAULT = {
    "groups": {"androidx.compose.ui": {"status": "extracted", "domain": "ui"}},
    "artifacts": [{"coordinate": "androidx.compose.ui:ui-android:1.0", "sha256": "a"}],
}
MARKDOWN = "com.example.md:markdown-android:1.0"


def _resolved(*conflicts: dict[str, str]) -> dict[str, Any]:
    return {
        "artifacts": [{"coordinate": MARKDOWN, "sha256": "b" * 64}],
        "conflicts": list(conflicts),
    }


def test_a_library_joins_the_closure_as_the_apps_own_group() -> None:
    closure = layered_closure(DEFAULT, _resolved())
    assert closure["groups"]["com.example.md"] == {
        "status": "extracted",
        "category": "app-surface",
        "domain": "com.example.md",
        "components": True,
        "origin": ORIGIN,
    }
    assert closure["artifacts"][-1] == {
        "coordinate": MARKDOWN,
        "sha256": "b" * 64,
        "domain": "com.example.md",
    }
    assert (
        closure["groups"]["androidx.compose.ui"]
        == DEFAULT["groups"]["androidx.compose.ui"]
    )


def test_a_library_moving_a_bom_module_or_owning_a_library_group_is_refused() -> None:
    moved = {"module": "androidx.compose.ui:ui", "resolved": "2.0", "bom": "1.0"}
    with pytest.raises(AppLibraryError, match="newer than the pinned BOM"):
        layered_closure(DEFAULT, _resolved(moved))
    google = {
        "artifacts": [{"coordinate": "androidx.compose.ui:ui-x:1.0", "sha256": "c"}]
    }
    with pytest.raises(AppLibraryError, match="already in the library's closure"):
        layered_closure(DEFAULT, {**google, "conflicts": []})


def _registry() -> Registry:
    return Registry.from_mapping(
        {
            "schemaVersion": "1.0.0",
            "minLibraryVersion": "0.1.0",
            "components": {"Text": _entry()},
            "actions": {},
        }
    )


def _entry() -> dict[str, Any]:
    return {
        "category": "app",
        "stability": "stable",
        "props": {"content": {"type": "string", "required": True}},
        "children": {"allowed": False},
    }


def test_the_runtime_catalog_takes_an_apps_components_but_keeps_its_own() -> None:
    registry = _registry()
    registry.extend({"Markdown": _entry()})
    assert "Markdown" in registry.components
    # A debug reload registers the slice again.
    registry.extend({"Markdown": _entry()})
    with pytest.raises(ComponentRegistryError, match="catalog's own"):
        registry.extend({"Text": _entry()})


def test_the_slice_codegen_merges_the_apps_lock_and_registers_it(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "compose.lock.json"
    lock.write_text(json.dumps({"components": {"Markdown": _entry()}}))
    own = app_components(lock)
    merged = with_app_lock({"components": {"Text": _entry()}}, own)
    assert sorted(merged["components"]) == ["Markdown", "Text"]
    assert app_components(None) == {}
    source = render_python_components(
        {**json.loads(json.dumps(REGISTRY.to_mapping())), "components": own}, "m3", own
    )
    assert "REGISTRY.extend(" in source
    assert "from pycompose.ir.generated_validators import REGISTRY" in source


def _project(tmp_path: Path, lock: dict[str, Any] | None = None) -> Project:
    (tmp_path / "gradlew").write_text("")
    if lock is not None:
        (tmp_path / "compose.lock.json").write_text(json.dumps(lock))
    return Project(root=tmp_path, config={})


def test_the_classpath_follows_the_lock(tmp_path: Path) -> None:
    project = _project(tmp_path, {"libraries": ["a:b:1"], "components": {}})
    add.sync_libraries(project)
    assert (tmp_path / add.LIBRARIES).read_text() == "a:b:1\n"
    (tmp_path / "compose.lock.json").write_text(json.dumps({"components": {}}))
    add.sync_libraries(project)
    assert not (tmp_path / add.LIBRARIES).exists()


def test_the_newest_version_fitting_the_bom_is_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tried = []

    def resolve(android: Path) -> dict[str, Any]:
        listed = (android / add.LIBRARIES).read_text().split(":")[-1].strip()
        tried.append(listed)
        moved = (
            [{"module": "m:m", "resolved": "2", "bom": "1"}] if listed == "2.0" else []
        )
        # The report covers the closure's own groups too; only the library's join.
        google = {"coordinate": "androidx.compose.ui:ui-android:1.0", "sha256": "a"}
        resolved = _resolved(*moved)
        return {**resolved, "artifacts": [google, *resolved["artifacts"]]}

    monkeypatch.setattr(add, "resolve", resolve)
    libraries, closure = add._fitting(
        tmp_path, DEFAULT, [], "com.example.md", "markdown", ["2.0", "1.9"]
    )
    assert tried == ["2.0", "1.9"]
    assert libraries == ["com.example.md:markdown:1.9"]
    assert "com.example.md" in closure["groups"]


def test_a_malformed_coordinate_is_refused_before_anything_runs(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="group:artifact"):
        add.add_library(_project(tmp_path), "not a coordinate")
