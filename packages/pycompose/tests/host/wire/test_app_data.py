"""App data in the envelope, and rehydration from the host's saved bytes."""

from __future__ import annotations

import json

import pytest

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, to_json, validate_ir
from pycompose.host.wire.data import read_data
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Text


def _snapshot(state: Snapshot, version: str = "1.4.0") -> dict:
    candidate = emit_ir(state, version)
    validate_ir(candidate)
    return json.loads(to_json(candidate))


def test_app_data_travels_in_metadata_only_when_the_app_publishes_it() -> None:
    assert "metadata" not in _snapshot(Snapshot(root=Text(id="t", text="ok")))
    snapshot = _snapshot(
        Snapshot(root=Text(id="t", text="ok"), data={"tasks": [], "draft": ""})
    )
    assert snapshot["metadata"]["data"] == {"tasks": [], "draft": ""}
    assert read_data(snapshot["metadata"]) == {"tasks": [], "draft": ""}


def test_app_data_is_copied_not_shared_with_the_snapshot() -> None:
    tasks = [{"id": 1, "title": "One", "done": False}]
    state = Snapshot(root=Text(id="t", text="ok"), data={"tasks": tasks})
    tasks.append({"id": 2, "title": "Two", "done": False})
    assert read_data(_snapshot(state)["metadata"]) == {
        "tasks": [{"id": 1, "title": "One", "done": False}]
    }


def test_app_data_coexists_with_bindings_and_effects() -> None:
    from pycompose.model.snapshot import Effect

    snapshot = _snapshot(
        Snapshot(
            root=Text(id="t", text="ok"),
            effects=(Effect("finish"),),
            data={"draft": "hi"},
        )
    )
    assert set(snapshot["metadata"]) == {"effects", "data"}


@pytest.mark.parametrize("version", ["1.0.0", "1.2.0", "1.3.0"])
def test_app_data_requires_its_schema(version: str) -> None:
    state = Snapshot(root=Text(id="t", text="ok"), data={"draft": "hi"})
    with pytest.raises(IrValidationError, match="newer schema"):
        validate_ir(emit_ir(state, version))


def test_malformed_metadata_data_is_rejected() -> None:
    base = emit_ir(Snapshot(root=Text(id="t", text="ok")), "1.4.0")
    broken = type(base)(
        root=base.root,
        schema_version=base.schema_version,
        version=base.version,
        metadata={"data": ["not", "an", "object"]},
    )
    with pytest.raises(IrValidationError, match="app data"):
        validate_ir(broken)


def test_reading_data_from_a_snapshot_without_any_returns_none() -> None:
    assert read_data(None) is None
    assert read_data({}) is None
