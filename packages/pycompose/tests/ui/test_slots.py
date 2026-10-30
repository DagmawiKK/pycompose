"""Declared slots: one component, several places its children can compose.

Compose's content parameters are not interchangeable -- a Scaffold's ``topBar``
is not its ``content`` -- so the wire says which slot a child fills, and both
sides check that the parent declared it. These tests pin the Python half of that
contract: how a slot is declared, written, and refused.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from readable import readable_reuse, rename

from pycompose.errors import IrError, IrValidationError
from pycompose.model.nodes.node import Node, Props
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Column, PlainTooltip, RichTooltip, Scaffold, Text, TooltipBox
from pycompose.ui.composition import slot_nodes
from pycompose.wire import emit_ir, to_dict, validate_ir


def text_node(node_id: str, content: str = "hi", **extra: object) -> Node:
    """Build an unvalidated node, for trees the generated constructors refuse.

    Args:
        node_id: Node id.
        content: The node's ``text`` prop.
        **extra: Further node fields, e.g. ``slot`` or ``children``.

    Returns:
        A raw ``Text`` node.
    """
    return Node(id=node_id, type="Text", props=Props({"text": content}), **extra)  # type: ignore[arg-type]


def snapshot(root: Node, schema_version: str = "1.0.0") -> dict:
    """Emit, validate and serialize one root.

    Args:
        root: The tree to publish.
        schema_version: Wire contract version the tree is written against.

    Returns:
        The canonical wire snapshot, each node named by its readable path.
    """
    reuse = readable_reuse()
    candidate = emit_ir(Snapshot(root=root), schema_version, reuse)
    assert validate_ir(candidate).snapshot is candidate
    return rename(to_dict(candidate), reuse)


def test_a_slot_name_must_be_camel_case() -> None:
    """The wire spelling is the schema's, not the app's."""
    with pytest.raises(IrError) as excinfo:
        Node(id="title", type="Text", slot="top_bar")
    assert "camelCase" in str(excinfo.value)


def test_slot_nodes_marks_every_node_and_refuses_a_function() -> None:
    """A slot is a structural fact, so a deferred function cannot supply it."""
    marked = slot_nodes(Text(id="title", text="Notes"), key="topBar", slot="topBar")
    assert [node.slot for node in marked] == ["topBar"]

    with pytest.raises(IrValidationError) as excinfo:
        slot_nodes(
            lambda _scope: Text(id="title", text="Notes"),
            key="topBar",
            slot="topBar",
        )
    assert "not a content function" in str(excinfo.value)


def test_a_slotted_child_is_written_after_its_props() -> None:
    """Canonical key order, and the primary children stay unslotted."""
    root = snapshot(
        Scaffold(
            id="screen",
            top_bar=Text(id="title", text="Notes"),
            children=Column(id="body", children=(Text(id="line", text="hello"),)),
        )
    )["root"]
    assert [child["type"] for child in root["children"]] == ["Column", "Text"]
    assert [child.get("slot") for child in root["children"]] == [None, "topBar"]
    title = root["children"][1]
    assert list(title) == ["id", "props", "slot", "type"]


def test_a_slot_filling_child_keeps_its_id() -> None:
    """Marking a child is not a new node: expansion and keys are unaffected."""
    explicit = Text(id="title", text="Notes")
    marked = slot_nodes(explicit, key="topBar", slot="topBar")[0]
    assert marked.id == explicit.id
    assert marked.props == explicit.props


def test_an_undeclared_slot_is_refused_in_debug() -> None:
    """Only the parent decides where a child may compose."""
    column = Node(
        id="body",
        type="Column",
        children=(text_node("line", slot="topBar"),),
    )
    with pytest.raises(IrValidationError) as excinfo:
        validate_ir(emit_ir(Snapshot(root=column), "1.0.0"))
    assert "unknown slot" in str(excinfo.value)


def test_a_leaf_component_refuses_children() -> None:
    """``Text`` declares neither primary children nor slots."""
    text = replace(text_node("root"), children=(text_node("child"),))
    with pytest.raises(IrValidationError) as excinfo:
        validate_ir(emit_ir(Snapshot(root=text), "1.0.0"))
    assert "children are not allowed" in str(excinfo.value)


def test_a_root_cannot_fill_a_slot() -> None:
    """Nothing encloses the root, so a slot on it names no slot at all."""
    root = text_node("root", slot="topBar")
    with pytest.raises(IrValidationError) as excinfo:
        validate_ir(emit_ir(Snapshot(root=root), "1.0.0"))
    assert "root cannot fill a slot" in str(excinfo.value)


def test_a_slotted_child_still_needs_a_declared_slot_on_the_wire() -> None:
    column = Node(
        id="body",
        type="Column",
        children=(text_node("line", slot="topBar"),),
    )
    with pytest.raises(IrValidationError, match="unknown slot"):
        validate_ir(emit_ir(Snapshot(root=column), "1.0.0"))


def test_tooltip_content_fills_the_box_slot_and_reaches_the_wire() -> None:
    """The anchor is ordinary content; the scoped tooltip is a declared slot."""
    root = snapshot(
        TooltipBox(
            id="tip",
            visible=True,
            is_persistent=True,
            tooltip=PlainTooltip(
                id="tip.tooltip",
                show_caret=True,
                children=(Text(id="tip.text", text="hint"),),
            ),
            children=(Text(id="tip.anchor", text="anchor"),),
        ),
        schema_version="1.23.0",
    )["root"]
    assert root["props"]["visible"] is True
    assert root["props"]["isPersistent"] is True
    assert [child.get("slot") for child in root["children"]] == [None, "tooltip"]
    tooltip = root["children"][1]
    assert tooltip["props"]["showCaret"] is True
    assert [child["id"] for child in tooltip["children"]] == [
        "root.tip.tooltip.tip.text"
    ]


def test_a_rich_tooltip_keeps_title_action_and_body_distinct() -> None:
    """A title is not an action, and neither is the primary body text."""
    root = snapshot(
        TooltipBox(
            id="tip",
            tooltip=RichTooltip(
                id="tip.tooltip",
                title=Text(id="tip.title", text="title"),
                action=Text(id="tip.action", text="action"),
                children=(Text(id="tip.text", text="body"),),
            ),
            children=(Text(id="tip.anchor", text="anchor"),),
        ),
        schema_version="1.23.0",
    )["root"]
    tooltip = next(
        child for child in root["children"] if child["type"] == "RichTooltip"
    )
    assert {child["id"]: child.get("slot") for child in tooltip["children"]} == {
        "root.tip.tooltip.tip.action": "action",
        "root.tip.tooltip.tip.text": None,
        "root.tip.tooltip.tip.title": "title",
    }


def test_the_generated_constructor_slots_reach_the_wire() -> None:
    """What the app writes is what the host reads, slot by slot."""
    root = snapshot(
        Scaffold(
            id="screen",
            top_bar=Text(id="title", text="Notes"),
            bottom_bar=Text(id="hint", text="1 note"),
            content=Column(id="body", children=(Text(id="line", text="hello"),)),
        )
    )["root"]
    assert [child.get("slot") for child in root["children"]] == [
        None,
        "bottomBar",
        "topBar",
    ]
    # `content` is the primary slot: its children are the unslotted ones.
    body = [child for child in root["children"] if child["type"] == "Column"]
    assert [child.get("slot") for child in body[0]["children"]] == [None]


def test_a_slot_is_declared_or_the_registry_refuses_the_schema() -> None:
    """The runtime registry keeps the vocabulary closed, not just the codegen."""
    from pycompose.errors import ComponentRegistryError
    from pycompose.model.catalog.registry import ComponentSpec

    with pytest.raises(ComponentRegistryError):
        ComponentSpec.from_mapping(
            "Scaffold",
            {
                "children": {"allowed": False},
                "slots": {"topBar": {"native": "topBar", "kind": "canvas"}},
            },
        )
