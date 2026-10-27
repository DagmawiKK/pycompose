"""Component construction through the public IR pipeline."""

import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path

import jsonschema
import pytest

from pycompose.components import (
    Box,
    Button,
    Checkbox,
    Column,
    FilterChip,
    LazyColumn,
    Modifier,
    Row,
    Scaffold,
    Spacer,
    Text,
    TextButton,
    TextField,
)
from pycompose.components.base import Component
from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir, to_json_bytes, validate_ir
from pycompose.state import State
from pycompose.testing.helpers import component_screen, read_golden


def test_text_constructs_a_registry_valid_node() -> None:
    text = Text(id="title", text="Hello", style="titleLarge")
    candidate = emit_ir(State(root=text), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    assert to_json_bytes(candidate) == (
        b'{"root":{"id":"root","props":{"style":"titleLarge","text":"Hello"},'
        b'"type":"Text"},"schemaVersion":"1.0.0","version":"0.1.0"}'
    )


@pytest.mark.parametrize(
    "component,props",
    [
        (Text, {"text": "Hi"}),
        (Column, {"horizontal_alignment": "center"}),
        (Row, {"vertical_alignment": "bottom"}),
        (Box, {"content_alignment": "center"}),
        (Spacer, {}),
        (Scaffold, {"container_color": "#FFFFFF"}),
        (Button, {"text": "Add", "on_click": "increment", "enabled": True}),
        (TextField, {"value": "", "on_value_change": "submit", "label": "Name"}),
        (LazyColumn, {"vertical_arrangement": "spaceBetween"}),
    ],
)
def test_first_batch_maps_python_props_to_registry_valid_ir(
    component: type[Component], props: dict[str, JsonValue]
) -> None:
    node = component(id="root", **props)
    candidate = emit_ir(State(root=node), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    assert node.type == component.component_type
    assert all("_" not in name for name in node.props)


def test_lazy_items_keep_stable_keys_after_reordering() -> None:
    first = Text(id="first", text="one")
    second = Text(id="second", text="two")
    a = emit_ir(State(root=LazyColumn(id="list", items=(first, second))), "1.0.0")
    b = emit_ir(State(root=LazyColumn(id="list", items=(second, first))), "1.0.0")
    assert [child.id for child in a.root.children] == ["root.first", "root.second"]
    assert [child.id for child in b.root.children] == ["root.second", "root.first"]
    with pytest.raises(IrValidationError, match="duplicate child key"):
        LazyColumn(id="list", items=(first, first))


def test_scaffold_content_becomes_children_not_a_wire_prop() -> None:
    content = Column(id="body", children=(Text(id="title", text="hello"),))
    node = Scaffold(id="screen", content=content)
    assert node.children == (content,)
    assert "content" not in node.props
    with pytest.raises(IrValidationError, match="both"):
        Scaffold(id="screen", content=content, children=(content,))


def test_modifier_chain_preserves_order_and_duplicates() -> None:
    empty = Modifier()
    modifier = (
        empty.padding(8)
        .fill_max_width(0.5)
        .size(48, 24)
        .clip("circle")
        .clickable("increment")
        .padding(4)
    )
    node = Spacer(id="gap", modifier=modifier)
    assert node.props.to_wire()["modifier"] == {
        "operations": [
            {"type": "padding", "value": 8},
            {"type": "fillMaxWidth", "fraction": 0.5},
            {"type": "size", "width": 48, "height": 24},
            {"type": "clip", "shape": "circle"},
            {"type": "clickable", "onClick": "increment", "enabled": True},
            {"type": "padding", "value": 4},
        ]
    }
    assert empty.to_wire() == {"operations": []}
    candidate = emit_ir(State(root=node), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate


def test_modifier_padding_keywords_build_the_side_form() -> None:
    mixed = Spacer(id="gap", modifier=Modifier().padding(bottom=8, horizontal=16))
    assert mixed.props.to_wire()["modifier"] == {
        "operations": [
            {
                "type": "padding",
                "value": {
                    "type": "PaddingValues",
                    "start": {"type": "Dp", "value": 16},
                    "end": {"type": "Dp", "value": 16},
                    "bottom": {"type": "Dp", "value": 8},
                },
            }
        ]
    }


def test_modifier_padding_sides_collapse_to_uniform_when_every_side_matches() -> None:
    uniform = Spacer(id="gap", modifier=Modifier().padding(4, top=4, vertical=4))
    assert uniform.props.to_wire()["modifier"] == {
        "operations": [{"type": "padding", "value": 4}]
    }


def test_modifier_padding_over_a_uniform_value_overrides_only_its_side() -> None:
    overridden = Spacer(id="gap", modifier=Modifier().padding(8, bottom=2))
    assert overridden.props.to_wire()["modifier"] == {
        "operations": [
            {
                "type": "padding",
                "value": {
                    "type": "PaddingValues",
                    "start": {"type": "Dp", "value": 8},
                    "top": {"type": "Dp", "value": 8},
                    "end": {"type": "Dp", "value": 8},
                    "bottom": {"type": "Dp", "value": 2},
                },
            }
        ]
    }


def test_modifier_padding_without_a_value_or_refusing_a_mixed_form_is_refused() -> None:
    with pytest.raises(IrValidationError, match="padding"):
        Modifier().padding()
    with pytest.raises(IrValidationError, match="dict"):
        Modifier().padding({"start": {"type": "Dp", "value": 4}}, top=1)


def test_semantics_carry_only_what_is_given_and_refuse_an_unknown_role() -> None:
    labelled = Modifier.semantics(content_description="Dark mode", role="switch")
    assert labelled.to_wire() == {
        "operations": [
            {"type": "semantics", "contentDescription": "Dark mode", "role": "switch"}
        ]
    }
    with pytest.raises(IrValidationError):
        Modifier.semantics(role="slider")


def test_the_wire_padding_object_matches_the_bundled_schema() -> None:
    padded = Spacer(
        id="gap",
        modifier=Modifier().padding(
            {"type": "PaddingValues", "start": {"type": "Dp", "value": 16}}
        ),
    )

    assert padded.props.to_wire()["modifier"] == {
        "operations": [
            {
                "type": "padding",
                "value": {
                    "type": "PaddingValues",
                    "start": {"type": "Dp", "value": 16},
                },
            }
        ]
    }
    # The host parses this same schema: an untagged side dict is not wire, so
    # Python refuses it at construction rather than rendering a blank frame.
    with pytest.raises(IrValidationError):
        Modifier().padding({"start": {"type": "Dp", "value": 16}})
    candidate = emit_ir(State(root=padded), SCHEMA_VERSION)
    jsonschema.validate(
        json.loads(to_json_bytes(candidate)),
        json.loads(
            (Path(__file__).parents[1] / "schema" / "ir.schema.json").read_text()
        ),
    )


@pytest.mark.parametrize(
    "component,valid",
    [
        (Text, {"text": "Hi"}),
        (Column, {}),
        (Row, {}),
        (Box, {}),
        (Spacer, {}),
        (Scaffold, {}),
        (Button, {"text": "Add", "on_click": "increment"}),
        (TextField, {"value": "", "on_value_change": "submit"}),
        (LazyColumn, {}),
        (Checkbox, {"checked": False, "on_checked_change": "increment"}),
        (TextButton, {"text": "Delete", "on_click": "increment"}),
        (FilterChip, {"label": "All", "selected": True, "on_click": "increment"}),
    ],
)
def test_every_component_fails_closed_on_unknown_props(
    component: type[Component], valid: dict[str, JsonValue]
) -> None:
    with pytest.raises(IrValidationError, match="unknown prop") as exc:
        component(id="bad", **valid, extra=1)
    assert exc.value.context["node_id"] == "bad"
    assert exc.value.context["prop"] == "extra"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Text(id="x"),
        lambda: Text(id="x", text=1),
        lambda: Text(id="x", text="hi", style="wrong"),
        lambda: Button(id="x", text="go", on_click="missing"),
        lambda: Button(id="x", text="go", on_click="submit", enabled=1),
        lambda: TextField(id="x", value=""),
        lambda: TextField(id="x", value=1, on_value_change="submit"),
        lambda: Row(id="x", vertical_alignment="wrong"),
        lambda: Column(id="x", horizontalAlignment="start"),
        lambda: Spacer(id="x", children=(Text(id="nested", text="no"),)),
        lambda: Checkbox(id="x"),
        lambda: Checkbox(id="x", checked="yes", on_checked_change="increment"),
        lambda: TextButton(id="x", text="Delete"),
        lambda: FilterChip(id="x", label="All", selected="yes", on_click="increment"),
        lambda: FilterChip(id="x", label="All", selected=True, on_click="missing"),
    ],
)
def test_invalid_component_values_fail_at_construction(
    build: Callable[[], Component],
) -> None:
    with pytest.raises(IrValidationError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: Modifier().padding(-1),
        lambda: Modifier().padding(True),
        lambda: Modifier().size(1, -1),
        lambda: Modifier().fill_max_width(1.5),
        lambda: Modifier().fill_max_width(float("nan")),
        lambda: Modifier().clip("missing"),
        lambda: Modifier().clickable("missing"),
        lambda: Modifier({"operations": [{"type": "missing"}]}),
        lambda: Modifier({"operations": [{"type": "padding"}]}),
        lambda: Modifier({"operations": [{"type": "padding", "value": 1, "extra": 1}]}),
    ],
)
def test_invalid_modifier_values_fail_at_construction(
    build: Callable[[], Modifier],
) -> None:
    with pytest.raises(IrValidationError):
        build()


def test_components_and_modifier_data_are_frozen() -> None:
    node = Text(id="text", text="hi", modifier=Modifier().padding(4))
    with pytest.raises(FrozenInstanceError):
        node.id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        node.props.values["text"] = "changed"  # type: ignore[index]
    modifier = Modifier().padding(4)
    wire = modifier.to_wire()
    wire["operations"] = []
    assert modifier.to_wire() == {"operations": [{"type": "padding", "value": 4}]}


def test_component_screen_matches_golden_and_generated_schema() -> None:
    candidate = emit_ir(State(root=component_screen()), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    actual = to_json_bytes(candidate)
    expected = read_golden("component_screen.json")
    assert actual == expected
    schema = json.loads(
        (Path(__file__).parents[1] / "schema" / "ir.schema.json").read_text()
    )
    jsonschema.validate(json.loads(actual), schema)


@pytest.mark.parametrize(
    "component,props",
    [
        (Checkbox, {"checked": True, "on_checked_change": "increment"}),
        (TextButton, {"text": "Delete", "on_click": "increment"}),
        (FilterChip, {"label": "All", "selected": False, "on_click": "increment"}),
    ],
)
def test_controls_added_in_1_3_0_map_python_props_to_registry_valid_ir(
    component: type[Component], props: dict[str, JsonValue]
) -> None:
    node = component(id="root", **props)
    candidate = emit_ir(State(root=node), "1.3.0")
    assert validate_ir(candidate).snapshot is candidate
    assert node.type == component.component_type
    assert all("_" not in name for name in node.props)


@pytest.mark.parametrize(
    "component,props",
    [
        (Checkbox, {"checked": True, "on_checked_change": "increment"}),
        (TextButton, {"text": "Delete", "on_click": "increment"}),
        (FilterChip, {"label": "All", "selected": True, "on_click": "increment"}),
    ],
)
def test_controls_added_after_1_3_0_need_that_schema(
    component: type[Component], props: dict[str, JsonValue]
) -> None:
    node = component(id="root", **props)
    assert emit_ir(State(root=node), "1.3.0").schema_version == "1.3.0"
    with pytest.raises(IrValidationError, match="newer schema"):
        validate_ir(emit_ir(State(root=node), "1.2.0"))
