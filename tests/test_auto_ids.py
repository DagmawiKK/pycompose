"""Auto-ids: a display node may leave its identity to the emitter's path."""

from __future__ import annotations

from typing import TypedDict

import pytest

from pycompose import action
from pycompose.components import Button, Column, Modifier, Text
from pycompose.core.node import Node
from pycompose.errors import IrError, IrValidationError
from pycompose.ir import emit_ir, to_json_bytes, validate_ir
from pycompose.state import State


class Nothing(TypedDict):
    pass


@action
def bump(state: State, payload: Nothing) -> State:
    """Return the snapshot unchanged.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The same snapshot.
    """
    return state


def ids_of(node: Node) -> list[str]:
    """Return every id in the tree, depth first.

    Args:
        node: The node to walk.

    Returns:
        Each node's id, parents before children.
    """
    return [node.id, *(i for child in node.children for i in ids_of(child))]


def test_a_display_node_without_an_id_gets_its_path_derived() -> None:
    state = State(
        root=Column(
            id="list",
            children=[Text(text="a"), Text(text="b"), Text(id="named", text="c")],
        )
    )

    emitted = emit_ir(state, "1.0.0")

    # The root's own id is always "root"; its display children derive their
    # index among the siblings, while the named child keeps its key.
    assert ids_of(emitted.root) == [
        "root",
        "root.0",
        "root.1",
        "root.named",
    ]
    assert validate_ir(emitted).snapshot is emitted


def test_derived_ids_are_byte_stable_across_rebuilds() -> None:
    def screen() -> State:
        return State(root=Column(id="list", children=[Text(text="a")]))

    assert to_json_bytes(emit_ir(screen(), "1.0.0")) == to_json_bytes(
        emit_ir(screen(), "1.0.0")
    )


def test_the_root_itself_may_omit_its_id() -> None:
    emitted = emit_ir(State(root=Text(text="hi")), "1.0.0")

    assert emitted.root.id == "root"


def test_an_auto_node_carrying_a_binding_is_refused() -> None:
    state = State(
        root=Column(
            id="screen",
            children=[Button(text="Add", on_click=bump.bind(id="tap"))],
        )
    )

    with pytest.raises(IrValidationError, match="explicit id"):
        emit_ir(state, "1.0.0")


def test_an_auto_node_whose_modifier_carries_an_action_is_refused() -> None:
    state = State(
        root=Column(
            id="screen",
            children=[
                Text(text="hi", modifier=Modifier().clickable(bump.bind(id="tap")))
            ],
        )
    )

    with pytest.raises(IrValidationError, match="explicit id"):
        emit_ir(state, "1.0.0")


def test_a_derived_id_colliding_with_a_named_sibling_is_refused() -> None:
    state = State(
        root=Column(id="screen", children=[Text(id="1", text="a"), Text(text="b")])
    )

    with pytest.raises(IrError, match="duplicate node id"):
        emit_ir(state, "1.0.0")
