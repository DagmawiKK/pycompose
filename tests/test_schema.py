"""SSOT registry + derived artifact tests (CI job 2 schema/golden selection)."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_PATH = ROOT / "schema" / "components.json"
IR_SCHEMA_PATH = ROOT / "schema" / "ir.schema.json"
VALIDATORS_PATH = ROOT / "pycompose" / "ir" / "generated_validators.py"
PAYLOADS_PATH = ROOT / "pycompose" / "bridge" / "generated_payloads.py"

PROP_TYPE_VOCABULARY = {
    "resource",
    "actionId",
    "boolean",
    "color",
    "dp",
    "durationMs",
    "enum",
    "integer",
    "modifier",
    "value",
    "number",
    "string",
}


def _registry() -> dict:
    from pycompose.schema.codegen.rules import with_rules

    return with_rules(json.loads(COMPONENTS_PATH.read_text(encoding="utf-8")))


def _gen() -> object:
    """The codegen emission module, imported the ordinary way.

    Emitters live beside the loader now: the renderers moved into
    ``emit_python`` / ``emit_wire`` and the loader into ``rules``, so the
    freshness checks grade the modules that actually produce each artifact.
    """
    return importlib.import_module("pycompose.schema.codegen.emit_python")


def _expected(renderer: str) -> str:
    return getattr(_gen(), renderer)(_registry())


def _valid_snapshot() -> dict:
    return {
        "version": "0.1.0",
        "schemaVersion": _registry()["schemaVersion"],
        "root": {
            "id": "root",
            "type": "Scaffold",
            "props": {},
            "children": [
                {"id": "root.0", "type": "Text", "props": {"text": "Hello"}},
            ],
        },
    }


def _expect_invalid(snapshot: dict, ir_schema: dict) -> None:
    try:
        jsonschema.validate(snapshot, ir_schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("expected validation to fail")


def test_components_json_shape() -> None:
    registry = _registry()
    assert isinstance(registry["schemaVersion"], str) and registry["schemaVersion"]
    assert registry["components"]
    for comp in registry["components"].values():
        assert comp["category"]
        assert comp["stability"] in {"stable", "experimental", "beta"}
        assert isinstance(comp["children"]["allowed"], bool)
        for prop in comp["props"].values():
            assert prop["type"] in PROP_TYPE_VOCABULARY
            if prop["type"] == "enum":
                assert prop["values"]
    for action in registry["actions"].values():
        assert isinstance(action, dict)


def test_ir_schema_is_fresh() -> None:
    assert IR_SCHEMA_PATH.read_text(encoding="utf-8") == importlib.import_module(
        "pycompose.schema.codegen.emit_wire"
    ).render_ir_schema(_registry())
    assert (
        ROOT / "pycompose" / "schema" / "ir.schema.json"
    ).read_bytes() == IR_SCHEMA_PATH.read_bytes()


def test_generated_validators_are_fresh() -> None:
    assert VALIDATORS_PATH.read_text(encoding="utf-8") == _expected("render_validators")


def test_generated_action_payloads_are_fresh() -> None:
    assert PAYLOADS_PATH.read_text(encoding="utf-8") == _expected("render_payloads")


def test_generated_tables_match_the_full_registry() -> None:
    from pycompose.ir.generated_validators import REGISTRY

    assert REGISTRY.to_mapping() == _registry()


def test_ir_schema_accepts_valid_snapshot() -> None:
    ir_schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(_valid_snapshot(), ir_schema)


def test_ir_schema_rejects_unknown_component() -> None:
    ir_schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    snapshot = _valid_snapshot()
    snapshot["root"]["type"] = "DoesNotExist"
    _expect_invalid(snapshot, ir_schema)


def test_ir_schema_rejects_missing_required_prop() -> None:
    ir_schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    snapshot = _valid_snapshot()
    del snapshot["root"]["children"][0]["props"]["text"]
    _expect_invalid(snapshot, ir_schema)


def test_ir_schema_rejects_disallowed_children() -> None:
    ir_schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    snapshot = _valid_snapshot()
    snapshot["root"]["type"] = "Text"
    snapshot["root"]["props"] = {"text": "root text"}
    snapshot["root"]["children"] = [
        {"id": "x", "type": "Text", "props": {"text": "nested"}}
    ]
    _expect_invalid(snapshot, ir_schema)


def test_ir_schema_rejects_bad_schema_version() -> None:
    ir_schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    snapshot = _valid_snapshot()
    snapshot["schemaVersion"] = "9.9.9"
    _expect_invalid(snapshot, ir_schema)


def test_ir_schema_rejects_unknown_action_id() -> None:
    ir_schema = json.loads(IR_SCHEMA_PATH.read_text(encoding="utf-8"))
    snapshot = _valid_snapshot()
    snapshot["root"] = {
        "id": "root",
        "type": "Button",
        "props": {"text": "Go", "onClick": "no_such_action"},
    }
    _expect_invalid(snapshot, ir_schema)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_registry_versions_are_semver() -> None:
    registry = _registry()
    for field in ("schemaVersion", "minLibraryVersion"):
        assert re.fullmatch(r"\d+\.\d+\.\d+", registry[field]), field


def test_library_version_satisfies_min_library() -> None:
    from pycompose.version import __version__

    min_library = _registry()["minLibraryVersion"]
    assert _version_tuple(__version__) >= _version_tuple(min_library)


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "padding", "value": -1},
        {"type": "fillMaxWidth", "fraction": 2},
        {"type": "clip", "shape": "missing"},
        {"type": "clickable", "onClick": "missing", "enabled": True},
        {"type": "size", "width": 1},
        {"type": "padding", "value": 1, "extra": 2},
        {"type": "missing"},
    ],
)
def test_ir_schema_rejects_invalid_modifier_operations(
    operation: dict[str, object],
) -> None:
    schema = json.loads(IR_SCHEMA_PATH.read_text())
    snapshot = _valid_snapshot()
    snapshot["root"]["props"] = {"modifier": {"operations": [operation]}}
    _expect_invalid(snapshot, schema)
