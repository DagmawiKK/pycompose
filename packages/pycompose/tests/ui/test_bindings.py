"""Bindings: a target the host keeps, stated once by Python."""

from __future__ import annotations

import pytest

from pycompose import Stream
from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Box, Color, Modifier, animate, follow, spring, tween


def test_a_binding_crosses_the_wire_as_its_target_its_travel_and_its_phase() -> None:
    modifier = Modifier().alpha(animate(0.5, tween(200)))
    assert modifier.to_wire()["operations"] == [
        {
            "type": "alpha",
            "alpha": {
                "type": "binding",
                "target": 0.5,
                "travel": {"kind": "tween", "durationMs": 200, "delayMs": 0},
                "phase": "composition",
            },
        }
    ]


def test_a_follow_in_composition_is_its_target_alone() -> None:
    modifier = Modifier().alpha(follow(0.5))
    assert modifier.to_wire()["operations"] == [{"type": "alpha", "alpha": 0.5}]


def test_a_follow_of_an_expression_is_the_expression_alone() -> None:
    modifier = Modifier().shadow(
        8, ambient_color=follow(Stream("list", "offset").as_alpha("#000000"))
    )
    assert modifier.to_wire()["operations"] == [
        {
            "type": "shadow",
            "elevation": 8,
            "ambientColor": {
                "type": "expression",
                "node": {
                    "op": "alpha",
                    "color": "#000000",
                    "args": [{"stream": "list", "name": "offset"}],
                },
            },
        }
    ]


def test_a_dp_and_a_colour_animate_and_validate_in_the_open_schema() -> None:
    node = Box(
        modifier=Modifier()
        .size(animate(48, spring(0.5)))
        .shadow(8, ambient_color=animate(Color(0xFF6750A4))),
    )
    snapshot = emit_ir(Snapshot(root=node), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot


def test_a_released_envelope_refuses_a_binding() -> None:
    snapshot = emit_ir(
        Snapshot(root=Box(modifier=Modifier().alpha(animate(1.0)))), "1.22.0"
    )
    with pytest.raises(IrValidationError, match="newer schema"):
        validate_ir(snapshot)


def test_a_prop_the_pin_gives_no_converter_is_refused() -> None:
    with pytest.raises(IrValidationError, match="no animation converter"):
        Modifier().test_tag(animate(1.0))  # type: ignore[arg-type]


def test_a_malformed_travel_is_refused() -> None:
    with pytest.raises(IrValidationError, match="none, a spring or a tween"):
        Modifier(
            {
                "operations": [
                    {
                        "type": "alpha",
                        "alpha": {
                            "type": "binding",
                            "target": 1.0,
                            "travel": {"kind": "bounce"},
                            "phase": "composition",
                        },
                    }
                ]
            }
        )


def test_an_unknown_phase_is_refused() -> None:
    with pytest.raises(IrValidationError, match="phase is composition"):
        Modifier(
            {
                "operations": [
                    {
                        "type": "alpha",
                        "alpha": {
                            "type": "binding",
                            "target": 1.0,
                            "travel": {"kind": "none"},
                            "phase": "pointer",
                        },
                    }
                ]
            }
        )
