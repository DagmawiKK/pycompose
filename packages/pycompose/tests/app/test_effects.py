"""One-shot effects: contract gating, ordering and fail-closed validation."""

from __future__ import annotations

import json

import pytest

from pycompose.app import Intent
from pycompose.errors import IrValidationError, StateError
from pycompose.host.wire import emit_ir, to_json, validate_ir
from pycompose.host.wire.effects import read_effects
from pycompose.host.wire.model import IRRoot
from pycompose.model.snapshot import Effect, Snapshot
from pycompose.ui import Button, Text
from pycompose.ui.intents import intent_name


def _snapshot(*effects: Effect, version: str = "1.4.0") -> dict:
    state = Snapshot(root=Text(id="text", text="hi"), effects=effects)
    candidate = emit_ir(state, version)
    validate_ir(candidate)
    return json.loads(to_json(candidate))


def test_effects_ride_the_envelope_in_declaration_order() -> None:
    snapshot = _snapshot(
        Effect("toast", {"message": "saved"}),
        Effect("finish"),
        Effect("navigate", {"route": "details"}),
    )
    assert snapshot["metadata"]["effects"] == [
        {"kind": "toast", "payload": {"message": "saved"}},
        {"kind": "finish", "payload": {}},
        {"kind": "navigate", "payload": {"route": "details"}},
    ]
    assert [effect.kind for effect in read_effects(snapshot["metadata"])] == [
        "toast",
        "finish",
        "navigate",
    ]


class Toggle(Intent):
    task_id: int


def test_effects_and_intent_contracts_share_one_metadata_object() -> None:
    state = Snapshot(
        root=Button(id="done", text="Done", on_click=Toggle(task_id=1)),
        effects=(Effect("toast", {"message": "saved"}),),
    )
    snapshot = json.loads(to_json(emit_ir(state, "1.4.0")))
    assert set(snapshot["metadata"]) == {"intents", "effects"}
    assert intent_name(Toggle) in snapshot["metadata"]["intents"]
    assert snapshot["root"]["props"]["onClick"]["fields"] == {"taskId": 1}
    assert snapshot["metadata"]["effects"][0]["kind"] == "toast"


def test_no_effects_leaves_metadata_untouched() -> None:
    snapshot = _snapshot()
    assert "metadata" not in snapshot


@pytest.mark.parametrize(
    "effects",
    [
        (Effect("reboot"),),
        (Effect("toast", {"message": "hi", "extra": 1}),),
        (Effect("toast", {}),),
        (Effect("toast", {"message": 7}),),
        (Effect("navigate", {"route": None}),),
        ("toast",),
    ],
)
def test_broken_effects_fail_closed(effects: tuple[object, ...]) -> None:
    with pytest.raises((IrValidationError, StateError)):
        state = Snapshot(root=Text(id="text", text="hi"), effects=effects)  # type: ignore[arg-type]
        validate_ir(emit_ir(state, "1.4.0"))


@pytest.mark.parametrize("version", ["1.0.0", "1.2.0", "1.3.0"])
def test_effects_require_their_schema(version: str) -> None:
    state = Snapshot(root=Text(id="text", text="hi"), effects=(Effect("finish"),))
    with pytest.raises(IrValidationError, match="newer schema"):
        validate_ir(emit_ir(state, version))


@pytest.mark.parametrize(
    "metadata",
    [
        {"effects": {}},
        {"effects": ["toast"]},
        {"effects": [{"kind": "toast"}]},
        {"effects": [{"kind": "reboot", "payload": {}}]},
        {"effects": [{"kind": "toast", "payload": {"message": 1}}]},
        {"effects": [{"kind": "toast", "payload": {}, "extra": 1}]},
    ],
)
def test_malformed_metadata_is_rejected(metadata: dict) -> None:
    base = emit_ir(Snapshot(root=Text(id="text", text="hi")), "1.4.0")
    broken = IRRoot(
        root=base.root,
        schema_version=base.schema_version,
        version=base.version,
        metadata=metadata,
    )
    with pytest.raises(IrValidationError, match="effect"):
        validate_ir(broken)


def test_a_typed_effect_names_its_fields_as_the_wire_does() -> None:
    from pycompose.app import PickFile

    effect = PickFile(request="b3").effect()
    assert effect.kind == "pickFile"
    assert dict(effect.payload) == {"request": "b3", "accept": "*/*"}
