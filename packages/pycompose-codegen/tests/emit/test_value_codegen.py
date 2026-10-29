"""Approved descriptors to generated artifacts and app dependency closure."""

import json
from pathlib import Path

import pytest
from families import RANGE_FAMILY
from pycompose_codegen.emit.app_slice import slice_registry
from pycompose_codegen.emit.values import definitions, render_python
from pycompose_codegen.emit.values_kotlin import (
    render_models,
    render_native,
)

ROOT = Path(__file__).resolve().parents[4]


def test_a_range_refuses_reversed_endpoints_before_native_construction() -> None:
    """A reversed range cannot be used by a native slider's value coercion."""
    from pycompose.errors import IrValidationError
    from pycompose.values import Range

    with pytest.raises(IrValidationError, match="ordered"):
        Range(1.0, 0.0)


"""The range descriptor (ADR-0017 decision 5) as the catalog will carry it."""


def _with_range() -> dict:
    """Return a catalog copy carrying the range descriptor.

    Returns:
        The parsed catalog with one injected family entry.
    """
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["valueTypes"]["Range"] = json.loads(json.dumps(RANGE_FAMILY))
    return registry


def test_an_operator_family_builds_its_form_rather_than_a_call() -> None:
    """A range crosses as tagged data and resolves through the operator form.

    ``ClosedFloatingPointRange`` has no factory to pin, so the citation is
    the language-level operator (ADR-0017 decision 5): the generated
    resolver builds ``start..end`` where every other family calls an
    artifact.
    """
    registry = _with_range()
    python = render_python(registry)
    assert "def Range(" in python
    assert '"Range",' in python
    native = render_native(registry)
    assert "value.start.toFloat()..value.end.toFloat()" in native
    # The dump spells the raw class, so the emitter states the type argument
    # the form itself binds: ``start..end`` is a range of the endpoint type.
    assert "Result<kotlin.ranges.ClosedFloatingPointRange<Float>>" in native
    assert (
        "fun range(value: RangeValue): "
        "kotlin.ranges.ClosedFloatingPointRange<Float>" in native
    )


def test_an_operator_family_needs_its_native_form(tmp_path: Path, monkeypatch) -> None:
    """The form is what the resolver emits; without it there is no resolver."""
    from pycompose_codegen.emit import main, rules

    registry = _with_range()
    del registry["valueTypes"]["Range"]["native"]["operator"]
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="needs a native '..'"):
        main.load_registry()


def test_an_operator_family_needs_its_language_level_citation(
    tmp_path: Path, monkeypatch
) -> None:
    """The citation is what tells re-derivation to skip, not invent, a source."""
    from pycompose_codegen.emit import main, rules

    registry = _with_range()
    del registry["valueTypes"]["Range"]["source"]["language"]
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="needs a language-level citation"):
        main.load_registry()


def test_app_values_include_transitive_dependencies_not_unrelated_factories() -> None:
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
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


def test_the_value_specs_literal_is_joined_from_a_flat_list() -> None:
    """Chunking keeps lines short; joining must not nest.

    A chain of ``+`` across the pieces is the same string to Kotlin's runtime,
    but every link is a call on the previous result, so the resolver recurses
    once per chunk -- and a contract long enough to need splitting overflows
    the compiler's stack before the file type-checks. The pieces are therefore
    one flat list, joined once, and no generated line may end in ``" +``.
    """
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    models = render_models(registry)
    assert ').joinToString("")' in models
    assert '" +\n' not in models


def test_codegen_rejects_unresolved_value_dependencies(
    tmp_path: Path, monkeypatch
) -> None:
    from pycompose_codegen.emit import main, rules

    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["valueTypes"]["TextStyle"]["parameters"]["fontSize"]["valueType"] = (
        "StateHandle"
    )
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="unknown value family"):
        main.load_registry()


def test_explicit_value_imports_are_kept_in_app_slice(tmp_path: Path) -> None:
    from pycompose_codegen.emit.main import build_app

    (tmp_path / "screen.py").write_text(
        "from m3 import Text\nfrom m3.values import Size\n"
    )
    assert build_app(tmp_path) == 0
    assert "def Size(" in (tmp_path / "m3/values.py").read_text()
    slice_root = tmp_path / ".pycompose/generated/ir/src/main/kotlin/com/pycompose/ir"
    assert "WireSize" in (slice_root / "generated" / "ValueModels.kt").read_text()


def test_codegen_refuses_untyped_native_defaults(tmp_path: Path, monkeypatch) -> None:
    from pycompose_codegen.emit import main, rules

    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    rule = registry["valueTypes"]["buttonElevation"]["parameters"]["defaultElevation"]
    rule.pop("default")
    rule["defaultNative"] = "arbitrary.native.Expression()"
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="missing native default provider"):
        main.load_registry()


def test_codegen_refuses_a_repeated_schema_version(tmp_path: Path, monkeypatch) -> None:
    from pycompose_codegen.emit import main, rules

    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["supportedSchemaVersions"].append(registry["schemaVersion"])
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="must be unique"):
        main.load_registry()


def test_codegen_refuses_unproven_opt_in_markers(tmp_path: Path, monkeypatch) -> None:
    from pycompose_codegen.emit import main, rules

    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["valueTypes"]["checkboxColors"]["optIn"] = [
        "androidx.compose.material3.ExperimentalMaterial3Api",
        "androidx.compose.material3.ExperimentalMaterial3Api",
    ]
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="optIn must be sorted"):
        main.load_registry()


def test_value_runtime_contract_excludes_native_build_metadata() -> None:
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    python = render_python(registry)
    models = render_models(registry)
    assert "androidx.compose" not in python + models
    assert "defaultNative" not in python + models
    assert "androidx.compose" in render_native(registry)


def test_approved_value_families_reach_every_generated_artifact() -> None:
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
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
    # 1.4.0 stabilized the date-picker colours factory, so only families the
    # pin still gates carry the marker.
    assert f"{marker}\n    fun timePickerLayoutType(value: JsonElement)" in native
    assert f"{marker}\n    fun datePickerColors" not in native
    assert f"{marker}\n    fun checkboxColors" not in native


def test_member_vocabularies_keep_each_holders_name() -> None:
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
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
    from pycompose_codegen.emit import main, rules

    path = tmp_path / "components.json"
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["valueTypes"]["Alignment"]["native"]["owners"]["TopMost"] = (
        "androidx.compose.ui.AbsoluteAlignment"
    )
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match=r"owners.TopMost is not a value"):
        main.load_registry()

    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["valueTypes"]["Alignment"]["native"]["owners"]["TopLeft"] = "not a holder"
    path.write_text(json.dumps(registry))
    with pytest.raises(SystemExit, match=r"owners.TopLeft is not a native holder"):
        main.load_registry()


def test_generated_kotlin_contract_reports_the_approved_schema_version() -> None:
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    assert f'const val SCHEMA_VERSION = "{registry["schemaVersion"]}"' in render_models(
        registry
    )
