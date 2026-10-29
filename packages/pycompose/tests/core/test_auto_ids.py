"""Call-site ids: a node without an id is keyed by the line that declares it."""

from __future__ import annotations

import pytest
from readable import ids, readable

from pycompose import composable
from pycompose.app import Intent
from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.core.node import Node
from pycompose.errors import IrError, IrValidationError
from pycompose.foundation import Column
from pycompose.material3 import Button, Text
from pycompose.state import State
from pycompose.ui import Modifier
from pycompose.wire import emit_ir, to_json_bytes, validate_ir


class Bump(Intent):
    """A tap that binds nothing."""


bump = Bump()


def ids_of(node: Node) -> list[str]:
    """Return every id in the tree, depth first.

    Args:
        node: The node to walk.

    Returns:
        Each node's id, parents before children.
    """
    return [node.id, *(i for child in node.children for i in ids_of(child))]


def test_a_node_without_an_id_is_keyed_by_its_call_site() -> None:
    state = State(
        root=Column(id="list", children=[Text(text="a"), Text(id="named", text="c")])
    )

    emitted = emit_ir(state, "1.0.0")

    unnamed, named = ids(readable(state, "1.0.0")["root"])[1:]
    assert unnamed.startswith(
        "root.test_a_node_without_an_id_is_keyed_by_its_call_site:"
    )
    assert named == "root.named"
    assert validate_ir(emitted).snapshot is emitted


def test_a_conditional_before_a_node_leaves_its_identity_alone() -> None:
    def screen(*, banner: bool) -> str:
        extra = [Text(text="banner")] if banner else []
        state = State(root=Column(id="list", children=[*extra, Text(text="body")]))
        return str(readable(state, "1.0.0")["root"]["children"][-1]["id"])

    assert screen(banner=True) == screen(banner=False)


def test_a_loop_numbers_the_nodes_one_call_site_declares() -> None:
    state = State(root=Column(id="list", children=[Text(text=t) for t in "ab"]))

    first, second = ids(readable(state, "1.0.0")["root"])[1:]

    assert first.endswith("#0")
    assert second.endswith("#1")


def test_derived_ids_are_byte_stable_across_rebuilds() -> None:
    def screen() -> State:
        return State(root=Column(id="list", children=[Text(text="a")]))

    assert to_json_bytes(emit_ir(screen(), "1.0.0")) == to_json_bytes(
        emit_ir(screen(), "1.0.0")
    )


def test_the_root_itself_may_omit_its_id() -> None:
    assert readable(State(root=Text(text="hi")), "1.0.0")["root"]["id"] == "root"


def test_a_node_carrying_a_binding_needs_no_id_outside_a_loop() -> None:
    state = State(
        root=Column(
            id="screen",
            children=[Button(text="Add", on_click=bump)],
        )
    )

    assert validate_ir(emit_ir(state, SCHEMA_VERSION)).snapshot is not None


def test_a_node_carrying_a_binding_in_a_loop_is_refused() -> None:
    state = State(
        root=Column(
            id="screen",
            children=[Button(text=label, on_click=bump) for label in "ab"],
        )
    )

    with pytest.raises(IrValidationError, match="explicit id"):
        emit_ir(state, "1.0.0")


def test_a_node_whose_modifier_carries_an_action_in_a_loop_is_refused() -> None:
    state = State(
        root=Column(
            id="screen",
            children=[Text(text=t, modifier=Modifier().clickable(bump)) for t in "ab"],
        )
    )

    with pytest.raises(IrValidationError, match="explicit id"):
        emit_ir(state, "1.0.0")


def test_a_composable_declared_in_a_loop_without_ids_is_refused() -> None:
    @composable
    def row(*, text: str) -> Node:
        return Text(text=text)

    state = State(root=Column(id="list", children=[row(text=t) for t in "ab"]))

    with pytest.raises(IrValidationError, match="needs an id"):
        emit_ir(state, "1.0.0")


def test_a_named_sibling_equal_to_a_derived_key_is_refused() -> None:
    first = Text(text="a")
    state = State(
        root=Column(id="screen", children=[first, Text(id=first.site, text="b")])
    )

    with pytest.raises(IrError, match="duplicate node id"):
        emit_ir(state, "1.0.0")


def test_a_refused_prop_names_its_line_and_the_closest_value() -> None:
    with pytest.raises(IrValidationError) as raised:
        Text(text="a", style="titelLarge")  # type: ignore[arg-type]

    assert raised.value.context["did_you_mean"] == "titleLarge"
    assert str(raised.value.context["source"]).startswith(__file__)
