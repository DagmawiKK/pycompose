"""Standalone IR validation through the CLI, without importing app code."""

import json
from pathlib import Path

import pytest
from pycompose_testing.helpers import read_golden
from test_cli_init import cli


def test_validate_accepts_a_canonical_fixture_outside_a_project(tmp_path: Path) -> None:
    path = tmp_path / "ui.json"
    path.write_bytes(read_golden("component_screen.json"))
    result = cli(tmp_path, "validate", str(path))
    assert result.returncode == 0, result.stderr
    assert "Valid IR" in result.stdout


def test_validate_accepts_tagged_nullable_and_numeric_value_unions(
    tmp_path: Path,
) -> None:
    from pycompose.components import Button, Column, Modifier, Text
    from pycompose.ir import emit_ir, to_json_bytes
    from pycompose.state import State
    from pycompose.values import Dp, Sp, TextStyle, ThemeColor

    root = Column(
        id="root",
        children=(
            Text(
                id="t",
                text="Hello",
                color=ThemeColor("primary"),
                style=TextStyle(font_size=Sp(20)),
                modifier=Modifier().size(Dp(80)),
            ),
            Button(id="b", text="Save", on_click="increment", elevation=None),
        ),
    )
    path = tmp_path / "ui.json"
    path.write_bytes(to_json_bytes(emit_ir(State(root=root), "1.11.0")))
    result = cli(tmp_path, "validate", str(path))
    assert result.returncode == 0, result.stderr
    document = json.loads(path.read_text())
    document["root"]["children"][0]["props"]["style"]["fontSize"]["type"] = "Dp"
    path.write_text(json.dumps(document))
    result = cli(tmp_path, "validate", str(path))
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize(
    "invalid",
    [
        {
            "version": "0.1.0",
            "schemaVersion": "1.0.0",
            "root": {"id": "root", "type": "Text"},
        },
        {
            "version": "0.1.0",
            "schemaVersion": "1.0.0",
            "root": {"id": "root", "type": "Text", "props": {"text": 3}},
        },
        {
            "version": "0.1.0",
            "schemaVersion": "1.0.0",
            "root": {"id": "root", "type": "Missing", "props": {}},
        },
        {
            "version": "0.1.0",
            "schemaVersion": "2.0.0",
            "root": {"id": "root", "type": "Text", "props": {"text": "hi"}},
        },
    ],
)
def test_validate_rejects_invalid_ir_with_actionable_diagnostics(
    tmp_path: Path, invalid: object
) -> None:
    path = tmp_path / "ui.json"
    path.write_text(json.dumps(invalid))
    result = cli(tmp_path, "validate", str(path))
    assert result.returncode == 2
    assert "pycompose validate:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "node",
    [
        {"id": "root", "type": "Text", "props": {"text": "hello", "extra": 1}},
        {"id": "root", "type": "Text", "props": {"text": "hello"}, "children": []},
        {"id": "", "type": "Text", "props": {"text": "hello"}},
        {"id": "root", "type": "Text", "props": []},
        {"id": "root", "type": "Text", "props": {"text": "hello"}, "extra": 1},
        {
            "id": "root",
            "type": "Button",
            "props": {"text": "go", "on_click": "submit"},
        },
        {
            "id": "root",
            "type": "Button",
            "props": {"text": "go", "onClick": "submit", "enabled": 1},
        },
        {
            "id": "root",
            "type": "Spacer",
            "props": {"modifier": {"operations": [{"type": "padding", "value": -1}]}},
        },
        {
            "id": "root",
            "type": "Spacer",
            "props": {
                "modifier": {"operations": [{"type": "fillMaxWidth", "fraction": 2}]}
            },
        },
        {
            "id": "root",
            "type": "Spacer",
            "props": {"modifier": {"operations": [{"type": "missing"}]}},
        },
        {
            "id": "root",
            "type": "Column",
            "props": {},
            "children": [
                {"id": "same", "type": "Text", "props": {"text": "a"}},
                {"id": "same", "type": "Text", "props": {"text": "b"}},
            ],
        },
    ],
)
def test_validate_checks_wire_rules_before_normalization_and_registry_identities(
    tmp_path: Path, node: object
) -> None:
    path = tmp_path / "ui.json"
    path.write_text(
        json.dumps({"version": "0.1.0", "schemaVersion": "1.0.0", "root": node})
    )
    before = path.read_bytes()
    result = cli(tmp_path, "validate", str(path))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "raw",
    [
        '{"version":"0.1.0","version":"0.2.0"}',
        '{"version":NaN}',
        "null",
        "[]",
        "not json",
    ],
)
def test_validate_rejects_malformed_or_ambiguous_json(tmp_path: Path, raw: str) -> None:
    (tmp_path / "ui.json").write_text(raw)
    result = cli(tmp_path, "validate", "ui.json")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_validate_checks_library_version_and_metadata_without_app_imports(
    tmp_path: Path,
) -> None:
    data = json.loads(read_golden("ir_counter.json"))
    data["metadata"] = {"locale": "en", "nested": [1, True, None]}
    (tmp_path / "ui.json").write_text(json.dumps(data, indent=2))
    (tmp_path / "main.py").write_text(
        'raise RuntimeError("app must not be imported")\n'
    )
    assert cli(tmp_path, "validate", "ui.json").returncode == 0
    data["metadata"] = []
    (tmp_path / "ui.json").write_text(json.dumps(data))
    assert cli(tmp_path, "validate", "ui.json").returncode == 2
    data.pop("metadata")
    data["version"] = "0.0.0"
    (tmp_path / "ui.json").write_text(json.dumps(data))
    result = cli(tmp_path, "validate", "ui.json")
    assert result.returncode == 2
    assert "version" in result.stderr


def test_validate_missing_file_is_actionable(tmp_path: Path) -> None:
    result = cli(tmp_path, "validate", "missing.json")
    assert result.returncode == 2
    assert "missing.json" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("metadata", [{"number": 1e999}, {"text": "\ud800"}])
def test_validate_rejects_non_canonical_scalars_even_in_metadata(
    tmp_path: Path, metadata: object
) -> None:
    data = json.loads(read_golden("ir_counter.json"))
    data["metadata"] = metadata
    raw = json.dumps(data).replace("Infinity", "1e999")
    (tmp_path / "ui.json").write_text(raw)
    result = cli(tmp_path, "validate", "ui.json")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_validate_rejects_non_utf8_node_ids(tmp_path: Path) -> None:
    data = json.loads(read_golden("ir_counter.json"))
    data["root"]["id"] = "\ud800"
    (tmp_path / "ui.json").write_text(json.dumps(data))
    result = cli(tmp_path, "validate", "ui.json")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
