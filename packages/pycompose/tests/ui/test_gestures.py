"""Gestures: the pin's detectors as modifiers, their events and their streams."""

from __future__ import annotations

import pytest

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.canonical import thaw_json
from pycompose.model.catalog.lock import REGISTRY, SCHEMA_VERSION
from pycompose.model.catalog.modifiers import gesture_streams
from pycompose.model.programs.expressions import Stream
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Box, Column, Intent, Modifier, Text, follow


class Dropped(Intent):
    pass


class Tapped(Intent):
    x: float
    y: float


def _box(modifier: Modifier) -> Box:
    return Box(id="box", modifier=modifier, children=[Text(text="drag me")])


def test_the_pin_s_detectors_are_modifiers_with_their_events_and_streams() -> None:
    drag = REGISTRY.modifiers["detectDragGestures"]
    assert set(drag) == {"onDragStart", "onDragEnd", "onDragCancel"}
    streams = gesture_streams(REGISTRY.derived_modifiers)
    assert streams["detectDragGestures"] == ("dragX", "dragY")
    assert set(REGISTRY.modifiers["detectTapGestures"]) == {
        "onTap",
        "onDoubleTap",
        "onLongPress",
    }
    assert "detectTransformGestures" not in REGISTRY.modifiers


def test_a_dragged_node_follows_its_own_stream_and_reports_the_drop() -> None:
    dragged = (
        Modifier()
        .offset(x=follow(Stream("box", "dragX")), y=follow(Stream("box", "dragY")))
        .detect_drag_gestures(on_drag_end=Dropped)
    )
    snapshot = emit_ir(Snapshot(root=_box(dragged)), SCHEMA_VERSION)
    validate_ir(snapshot)
    operations = thaw_json(snapshot.root.props.get("modifier"))["operations"]
    assert operations[1]["type"] == "detectDragGestures"


def test_a_tap_reports_its_position() -> None:
    tapped = Modifier().detect_tap_gestures(on_tap=Tapped)
    validate_ir(emit_ir(Snapshot(root=_box(tapped)), SCHEMA_VERSION))


def test_a_stream_of_a_node_wearing_no_gesture_is_refused() -> None:
    reader = Text(
        text="x", modifier=Modifier().offset(x=follow(Stream("box", "dragX")))
    )
    root = Column(children=[Box(id="box", children=[]), reader])
    with pytest.raises(IrValidationError, match="dragX"):
        validate_ir(emit_ir(Snapshot(root=root), SCHEMA_VERSION))
