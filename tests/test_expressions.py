"""Expressions over holder streams: authoring, emission and validation (plan 31 §6)."""

from __future__ import annotations

import json

import pytest

from pycompose import Stream
from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.errors import IrValidationError
from pycompose.foundation import Column
from pycompose.material3 import ModalNavigationDrawer, Text
from pycompose.state import State
from pycompose.wire import emit_ir, to_json, validate_ir


def _scrim(key: str = "nav") -> object:
    return Stream(key, "progress").times(0.6).as_alpha("#000000")


def test_an_expression_is_typed_as_it_is_built() -> None:
    assert _scrim().to_wire() == {
        "type": "expression",
        "node": {
            "op": "alpha",
            "color": "#000000",
            "args": [
                {
                    "op": "times",
                    "args": [{"stream": "nav", "name": "progress"}, {"number": 0.6}],
                }
            ],
        },
    }
    with pytest.raises(TypeError, match="no arithmetic"):
        _scrim().times(2)
    with pytest.raises(ValueError, match="no state family exposes"):
        Stream("nav", "velocity")
    with pytest.raises(ValueError, match="#RRGGBB"):
        Stream("nav", "progress").as_alpha("black")
    with pytest.raises(ValueError, match="reversed"):
        Stream("nav", "progress").clamp(1, 0)


def test_an_expression_stays_within_its_limits() -> None:
    deep = Stream("nav", "progress")
    with pytest.raises(IrValidationError, match="exceeds"):
        for _ in range(16):
            deep = deep.times(1.0)


def _drawer(scrim: object, key: str = "nav") -> State:
    return State(
        root=ModalNavigationDrawer(
            Column(Text(text="Body")),
            id=key,
            scrim_color=scrim,
            drawer=Text(text="Menu"),
        )
    )


def test_emission_names_the_holder_by_its_wire_id() -> None:
    snapshot = emit_ir(_drawer(_scrim()), SCHEMA_VERSION)
    validate_ir(snapshot)
    wire = json.loads(to_json(snapshot))
    stream = wire["root"]["props"]["scrimColor"]["node"]["args"][0]["args"][0]
    assert stream == {"stream": wire["root"]["id"], "name": "progress"}


def test_a_stream_naming_no_component_is_refused_at_emission() -> None:
    with pytest.raises(IrValidationError, match="names no component"):
        emit_ir(_drawer(_scrim("menu")), SCHEMA_VERSION)


def test_a_stream_its_holder_does_not_expose_is_refused() -> None:
    state = State(
        root=Column(
            Text(
                text="Hi",
                id="label",
                color=Stream("label", "progress").as_alpha("#000000"),
            ),
        )
    )
    snapshot = emit_ir(state, SCHEMA_VERSION)
    with pytest.raises(IrValidationError, match="names no holder exposing it"):
        validate_ir(snapshot)


def test_only_a_colour_takes_an_expression() -> None:
    with pytest.raises(IrValidationError):
        Text(text=_scrim())  # type: ignore[arg-type]
