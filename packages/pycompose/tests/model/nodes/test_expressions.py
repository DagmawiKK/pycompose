"""Expressions over holder streams: authoring, emission and validation (plan 31 §6)."""

from __future__ import annotations

import json

import pytest

from pycompose import Stream
from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, to_json, validate_ir
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.snapshot import Snapshot
from pycompose.ui import (
    BasicText,
    Box,
    Column,
    ModalNavigationDrawer,
    Modifier,
    Surface,
    Text,
    animate,
    follow,
    tween,
)


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


def _drawer(scrim: object, key: str = "nav") -> Snapshot:
    return Snapshot(
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
    state = Snapshot(
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


def test_only_a_numeric_or_colour_prop_takes_an_expression() -> None:
    with pytest.raises(IrValidationError):
        Text(text=_scrim())  # type: ignore[arg-type]
    # An integer is discrete: an expression is evaluated in floating point.
    with pytest.raises(IrValidationError, match="invalid prop value"):
        BasicText(text="Hi", min_lines=Stream("list", "progress"))  # type: ignore[arg-type]


def test_a_number_expression_drives_a_number_prop() -> None:
    state = Snapshot(
        root=Column(
            Surface(shadow_elevation=Stream("list", "progress").times(4)),
            id="list",
        )
    )
    snapshot = emit_ir(state, SCHEMA_VERSION)
    validate_ir(snapshot)
    wire = json.loads(to_json(snapshot))
    expression = wire["root"]["children"][0]["props"]["shadowElevation"]
    assert expression["type"] == "expression"
    assert expression["node"]["args"][0] == {
        "stream": wire["root"]["id"],
        "name": "progress",
    }


def test_a_number_expression_drives_a_modifier_argument() -> None:
    state = Snapshot(
        root=Column(
            Box(modifier=Modifier().offset(y=Stream("list", "offset"))),
            id="list",
        )
    )
    snapshot = emit_ir(state, SCHEMA_VERSION)
    validate_ir(snapshot)
    wire = json.loads(to_json(snapshot))
    operation = wire["root"]["children"][0]["props"]["modifier"]["operations"][0]
    assert operation["y"] == {
        "type": "expression",
        "node": {"stream": wire["root"]["id"], "name": "offset"},
    }


def test_a_bound_number_expression_resolves_its_stream() -> None:
    state = Snapshot(
        root=Column(
            Surface(shadow_elevation=animate(Stream("list", "progress"), tween(100))),
            id="list",
        )
    )
    snapshot = emit_ir(state, SCHEMA_VERSION)
    validate_ir(snapshot)
    wire = json.loads(to_json(snapshot))
    binding = wire["root"]["children"][0]["props"]["shadowElevation"]
    assert binding["type"] == "binding"
    assert binding["target"]["node"]["stream"] == wire["root"]["id"]


def test_a_bound_expression_naming_no_holder_is_refused() -> None:
    with pytest.raises(IrValidationError, match="names no component"):
        emit_ir(
            Snapshot(root=Surface(shadow_elevation=follow(Stream("gone", "progress")))),
            SCHEMA_VERSION,
        )


def test_a_compound_dp_family_refuses_a_number_expression() -> None:
    """A dp prop carrying PaddingValues holds a compound value, not a number."""
    with pytest.raises(IrValidationError, match="invalid modifier prop"):
        Column(
            Box(modifier=Modifier().padding(Stream("list", "progress"))),  # type: ignore[arg-type]
            id="list",
        )


def test_a_dp_family_takes_a_number_expression() -> None:
    """A dp the app states as a Dp is a number, and a number may be live."""
    state = Snapshot(
        root=Column(
            Box(modifier=Modifier().size(width=Stream("list", "progress").times(40))),
            id="list",
        )
    )
    snapshot = emit_ir(state, SCHEMA_VERSION)
    validate_ir(snapshot)
