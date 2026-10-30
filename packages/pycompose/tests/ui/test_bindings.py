"""Bindings: a target the host animates to, stated once by Python."""

from __future__ import annotations

import pytest

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Box, Color, Modifier, animate, spring, tween


def test_a_binding_crosses_the_wire_as_its_target_and_travel() -> None:
    modifier = Modifier().alpha(animate(0.5, tween(200)))
    assert modifier.to_wire()["operations"] == [
        {
            "type": "alpha",
            "alpha": {
                "type": "animate",
                "to": 0.5,
                "spec": {"kind": "tween", "durationMs": 200, "delayMs": 0},
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


def test_only_a_number_a_dp_or_a_colour_animates() -> None:
    with pytest.raises(IrValidationError, match="cannot animate"):
        Modifier().test_tag(animate(1.0))  # type: ignore[arg-type]


def test_a_malformed_travel_is_refused() -> None:
    with pytest.raises(IrValidationError, match="spring or a tween"):
        Modifier(
            {
                "operations": [
                    {
                        "type": "alpha",
                        "alpha": {
                            "type": "animate",
                            "to": 1.0,
                            "spec": {"kind": "bounce"},
                        },
                    }
                ]
            }
        )
