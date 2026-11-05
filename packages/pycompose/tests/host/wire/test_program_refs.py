"""A snapshot carries each program once, and a prop names it by its content."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
from goldens import GOLDENS

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.host.wire.patch import diff_nodes, full_bytes, patch_bytes
from pycompose.host.wire.serializer import to_json_bytes
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.programs.refs import program_hash
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Canvas, Column, host, rect


@host
def bar(width: float, height: float, level: float) -> None:
    rect(0xFF6750A4, 0, 0, width * level, height)


def _rows(*levels: float) -> Snapshot:
    return Snapshot(
        root=Column(
            children=[
                Canvas(id=f"row{i}", on_draw=bar.bind(level))
                for i, level in enumerate(levels)
            ]
        )
    )


def test_one_program_on_many_nodes_crosses_once() -> None:
    snapshot = emit_ir(_rows(0.25, 0.5, 0.75), SCHEMA_VERSION)
    validate_ir(snapshot)
    programs = (snapshot.metadata or {})["programs"]
    assert list(programs) == [program_hash(bar.to_wire())]


def test_refs_and_their_section_are_what_the_wire_schema_describes() -> None:
    schema_path = Path(__file__).resolve().parents[5] / "schema" / "ir.schema.json"
    snapshot = emit_ir(_rows(0.5), SCHEMA_VERSION)
    document = json.loads(to_json_bytes(snapshot))
    jsonschema.validate(document, json.loads(schema_path.read_text()))
    document["root"]["children"][0]["props"]["onDraw"]["program"]["hash"] = "zz"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, json.loads(schema_path.read_text()))


def test_a_patch_keeps_the_programs_when_only_bound_arguments_change() -> None:
    base = emit_ir(_rows(0.25, 0.5), SCHEMA_VERSION)
    new = emit_ir(_rows(0.25, 0.75), SCHEMA_VERSION)
    envelope = json.loads(
        patch_bytes(
            new,
            diff_nodes(base.root, new.root),
            base_serial=1,
            serial=2,
            surface="main",
            base=base,
        )
    )
    assert envelope["keep"] == ["programs"]
    assert "body" not in json.dumps(envelope["ops"])


def test_a_prop_naming_a_program_the_snapshot_lacks_is_refused() -> None:
    snapshot = emit_ir(_rows(0.5), SCHEMA_VERSION)
    with pytest.raises(IrValidationError, match="lacks"):
        validate_ir(replace(snapshot, metadata=None))


def test_a_program_not_named_by_its_content_is_refused() -> None:
    snapshot = emit_ir(_rows(0.5), SCHEMA_VERSION)
    ((name, program),) = (snapshot.metadata or {})["programs"].items()
    misnamed = {"programs": {name: {**program, "params": ["number", "number"]}}}
    with pytest.raises(IrValidationError, match="invalid programs"):
        validate_ir(replace(snapshot, metadata=misnamed))


def _envelopes() -> dict[str, object]:
    base = emit_ir(_rows(0.25, 0.5), SCHEMA_VERSION)
    new = emit_ir(_rows(0.25, 0.75), SCHEMA_VERSION)
    ops = diff_nodes(base.root, new.root)
    full = full_bytes(base, serial=1, surface="main")
    patch = patch_bytes(new, ops, base_serial=1, serial=2, surface="main", base=base)
    return {"full": json.loads(full), "patch": json.loads(patch)}


def test_the_envelopes_the_host_applies_match_the_golden() -> None:
    # The host applies the same pair: the patch must find its programs kept.
    path = GOLDENS / "programs" / "refs.json"
    written = json.dumps(_envelopes(), indent=1, sort_keys=True) + "\n"
    assert path.read_text(encoding="utf-8") == written
