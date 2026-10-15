"""Approved descriptors to generated artifacts and app dependency closure."""

import json
from pathlib import Path

import pytest

from pycompose.schema.codegen.app_slice import slice_registry
from pycompose.schema.codegen.values import (
    definitions,
    render_models,
    render_native,
    render_python,
)

ROOT = Path(__file__).resolve().parents[1]


def test_app_values_include_transitive_dependencies_not_unrelated_factories() -> None:
    registry = json.loads((ROOT / "schema/components.json").read_text())
    sliced = slice_registry(registry, {"Text"})
    specs = definitions(sliced)
    assert "Sp" in specs
    assert "FontFamily" in specs
    assert "ThemeColor" in specs
    assert "buttonColors" not in specs
    python = render_python(sliced)
    models = render_models(sliced)
    native = render_native(sliced)
    assert "def TextStyle(" in python
    assert "WireTextStyle" in models
    assert "MaterialTheme.colorScheme.primary" in native
    assert "ButtonColors" not in models + native


def test_codegen_rejects_unresolved_value_dependencies(
    tmp_path: Path, monkeypatch
) -> None:
    from pycompose.schema.codegen import main

    registry = json.loads((ROOT / "schema/components.json").read_text())
    registry["valueTypes"]["TextStyle"]["parameters"]["fontSize"]["valueType"] = (
        "StateHandle"
    )
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="unknown value family"):
        main.load_registry()


def test_explicit_value_imports_are_kept_in_app_slice(tmp_path: Path) -> None:
    from pycompose.schema.codegen.main import build_app

    (tmp_path / "screen.py").write_text(
        "from m3 import Text\nfrom m3.values import Size\n"
    )
    assert build_app(tmp_path) == 0
    assert "def Size(" in (tmp_path / "m3/values.py").read_text()
    assert (
        "WireSize"
        in (
            tmp_path
            / "android/ir/src/main/kotlin/com/pycompose/ir/generated/ValueModels.kt"
        ).read_text()
    )


def test_codegen_refuses_untyped_native_defaults(tmp_path: Path, monkeypatch) -> None:
    from pycompose.schema.codegen import main

    registry = json.loads((ROOT / "schema/components.json").read_text())
    rule = registry["valueTypes"]["buttonElevation"]["parameters"]["defaultElevation"]
    rule.pop("default")
    rule["defaultNative"] = "arbitrary.native.Expression()"
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="missing native default provider"):
        main.load_registry()


def test_codegen_refuses_a_repeated_schema_version(tmp_path: Path, monkeypatch) -> None:
    from pycompose.schema.codegen import main

    registry = json.loads((ROOT / "schema/components.json").read_text())
    registry["supportedSchemaVersions"].append(registry["schemaVersion"])
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="must be unique"):
        main.load_registry()


def test_codegen_refuses_unproven_opt_in_markers(tmp_path: Path, monkeypatch) -> None:
    from pycompose.schema.codegen import main

    registry = json.loads((ROOT / "schema/components.json").read_text())
    registry["valueTypes"]["checkboxColors"]["optIn"] = [
        "androidx.compose.material3.ExperimentalMaterial3Api",
        "androidx.compose.material3.ExperimentalMaterial3Api",
    ]
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="optIn must be sorted"):
        main.load_registry()


def test_value_runtime_contract_excludes_native_build_metadata() -> None:
    registry = json.loads((ROOT / "schema/components.json").read_text())
    python = render_python(registry)
    models = render_models(registry)
    assert "androidx.compose" not in python + models
    assert "defaultNative" not in python + models
    assert "androidx.compose" in render_native(registry)


def test_approved_value_families_reach_every_generated_artifact() -> None:
    registry = json.loads((ROOT / "schema/components.json").read_text())
    specs = definitions(registry)
    assert specs["ToggleableState"]["kind"] == "constant"
    assert specs["BorderStroke"]["parameters"]["brush"]["valueType"] == "Brush"
    assert specs["AnnotatedString"]["parameters"] == {
        "text": {"type": "string", "required": True}
    }
    python = render_python(registry)
    assert {"def ToggleableState(", "def BorderStroke(", "def AnnotatedString("} <= set(
        python.splitlines()
    )
    models = render_models(registry)
    assert all(
        name in models
        for name in ("WireToggleableState", "WireBorderStroke", "WireAnnotatedString")
    )
    native = render_native(registry)
    assert '"On" -> androidx.compose.ui.state.ToggleableState.On' in native
    assert "androidx.compose.foundation.BorderStroke(" in native
    marker = "@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)"
    assert f"{marker}\n    fun datePickerColors(value: JsonElement)" in native
    assert f"{marker}\n    fun datePickerColors(value: DatePickerColorsValue)" in native
    assert f"{marker}\n    fun checkboxColors" not in native


def test_member_vocabularies_keep_each_holders_name() -> None:
    registry = json.loads((ROOT / "schema/components.json").read_text())
    specs = definitions(registry)
    alignment = specs["Alignment"]
    assert alignment["native"]["propertyOwner"] == "androidx.compose.ui.Alignment"
    assert (
        alignment["native"]["owners"]["TopLeft"]
        == "androidx.compose.ui.AbsoluteAlignment"
    )
    # Alignment.Vertical is a sibling of Alignment, not a subtype: its members
    # stay in their own family.
    assert "Top" not in alignment["parameters"]["name"]["values"]
    native = render_native(registry)
    assert '"TopStart" -> androidx.compose.ui.Alignment.TopStart' in native
    assert '"TopLeft" -> androidx.compose.ui.AbsoluteAlignment.TopLeft' in native
    assert (
        '"CenterVertically" -> androidx.compose.ui.Alignment.CenterVertically' in native
    )


def test_codegen_refuses_an_unproven_member_holder(tmp_path: Path, monkeypatch) -> None:
    from pycompose.schema.codegen import main

    path = tmp_path / "components.json"
    registry = json.loads((ROOT / "schema/components.json").read_text())
    registry["valueTypes"]["Alignment"]["native"]["owners"]["TopMost"] = (
        "androidx.compose.ui.AbsoluteAlignment"
    )
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match=r"owners.TopMost is not a value"):
        main.load_registry()

    registry = json.loads((ROOT / "schema/components.json").read_text())
    registry["valueTypes"]["Alignment"]["native"]["owners"]["TopLeft"] = "not a holder"
    path.write_text(json.dumps(registry))
    with pytest.raises(SystemExit, match=r"owners.TopLeft is not a native holder"):
        main.load_registry()


def test_generated_kotlin_contract_reports_the_approved_schema_version() -> None:
    registry = json.loads((ROOT / "schema/components.json").read_text())
    assert f'const val SCHEMA_VERSION = "{registry["schemaVersion"]}"' in render_models(
        registry
    )
