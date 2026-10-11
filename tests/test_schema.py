"""SSOT registry + derived artifact tests (CI job 2 schema/golden selection)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_PATH = ROOT / "schema" / "components.json"
IR_SCHEMA_PATH = ROOT / "schema" / "ir.schema.json"
VALIDATORS_PATH = ROOT / "pycompose" / "ir" / "generated_validators.py"
GEN_PATH = ROOT / "tools" / "schema" / "gen.py"

PROP_TYPE_VOCABULARY = {
    "actionId",
    "boolean",
    "color",
    "dp",
    "durationMs",
    "enum",
    "integer",
    "modifier",
    "number",
    "string",
}


def _registry() -> dict:
    return json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))


def _gen() -> object:
    spec = importlib.util.spec_from_file_location("_pycompose_gen", GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert IR_SCHEMA_PATH.read_text(encoding="utf-8") == _expected("render_ir_schema")


def test_generated_validators_are_fresh() -> None:
    assert VALIDATORS_PATH.read_text(encoding="utf-8") == _expected("render_validators")


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
