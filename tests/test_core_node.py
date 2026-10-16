"""core.Node / core.Props: frozen identity and camelCase enforcement."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pycompose.core.node import Node, Props
from pycompose.core.props import props_from_kwargs
from pycompose.errors import IrError


def test_props_requires_camel_case_with_context() -> None:
    with pytest.raises(IrError) as excinfo:
        Props({"on_click": "increment"})
    message = str(excinfo.value)
    assert "not camelCase" in message
    assert "prop='on_click'" in message


def test_props_from_kwargs_then_wire() -> None:
    props = Props(props_from_kwargs(on_value_change="hi", label="Name"))
    assert props.to_wire() == {"onValueChange": "hi", "label": "Name"}


def test_props_is_frozen_and_mapping_like() -> None:
    props = Props({"text": "hi"})
    with pytest.raises(TypeError):
        props.values["text"] = "no"  # type: ignore[index]
    assert props["text"] == "hi"
    assert props.get("missing") is None
    assert "text" in props
    assert len(props) == 1


def test_node_rejects_empty_id_with_context() -> None:
    with pytest.raises(IrError) as excinfo:
        Node(id="", type="Text")
    assert "node_type='Text'" in str(excinfo.value)


def test_node_rejects_empty_type_with_context() -> None:
    with pytest.raises(IrError) as excinfo:
        Node(id="root", type="")
    assert "node_id='root'" in str(excinfo.value)


def test_node_is_frozen() -> None:
    node = Node(id="root", type="Column")
    with pytest.raises(FrozenInstanceError):
        node.id = "other"  # type: ignore[misc]


def test_node_normalizes_children_to_tuple() -> None:
    child = Node(id="root.0", type="Text", props=Props({"text": "hi"}))
    node = Node(id="root", type="Column", children=[child])  # type: ignore[arg-type]
    assert node.children == (child,)


def test_node_is_marked_with_a_slot_it_already_fills() -> None:
    """Marking is idempotent, so an unchanged branch stays the same object.

    Expansion keeps untouched branches by reference; a needless copy would
    break that, and the slot is the only field that may differ anyway.
    """
    title = Node(id="title", type="Text", slot="topBar")
    assert title.with_slot("topBar") is title


def test_node_refuses_a_slot_that_is_not_camel_case() -> None:
    """The copy is the one place a slot lands, so it checks the spelling."""
    with pytest.raises(IrError) as excinfo:
        Node(id="title", type="Text").with_slot("top_bar")
    assert "camelCase" in str(excinfo.value)
