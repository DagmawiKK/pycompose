"""Prop passing: scalars, dp, callbacks, named constants and import hygiene."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pycompose_codegen.emit.adapters.assemble import render
from pycompose_codegen.emit.adapters.eligibility import held_props
from test_generated_adapters import (
    GENERATED,
    SCHEMA_PATH,
    components,
)


def test_a_dp_prop_is_read_in_the_unit_the_app_stated() -> None:
    """``thickness=2`` is two density-independent pixels, not two pixels.

    The model holds a plain number, so the adapter names the unit where it is
    read; an absent one falls back to the pinned default rather than to a zero
    the host invented.
    """
    block = render("HorizontalDivider", components()["HorizontalDivider"])
    assert "val thicknessWire = model.props.thickness" in block
    assert (
        "val thicknessValue = if (thicknessWire != null) thicknessWire.dp "
        "else androidx.compose.material3.DividerDefaults.Thickness" in block
    )
    assert "thickness = thicknessValue," in block


@pytest.mark.parametrize(
    "spec",
    [{"type": "dp", "required": True}, {"type": "dp", "default": 4}],
)
def test_a_dp_prop_that_is_always_present_wraps_at_the_call(spec: dict) -> None:
    """No fallback to choose: the number is there, and it is a dp."""
    entry = components()["VerticalDivider"]
    entry["props"]["thickness"] = spec
    block = render("VerticalDivider", entry)
    assert "thickness = model.props.thickness.dp," in block


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            lambda registry: registry["components"]["HorizontalDivider"][
                "props"
            ].update({"thickness": {"type": "dp"}}),
            "dp props must be required or carry",
        ),
        (
            lambda registry: registry["components"]["HorizontalDivider"]["props"][
                "thickness"
            ].update({"nativeDefault": ""}),
            "'nativeDefault' must be Kotlin source",
        ),
        (
            lambda registry: registry["components"]["Text"]["props"]["text"].update(
                {"nativeDefault": "androidx.compose.material3.LocalTextStyle.current"}
            ),
            "'nativeDefault' is read only for value, dp and named-constant props",
        ),
    ],
)
def test_the_schema_refuses_a_dp_prop_it_cannot_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit: Any,
    message: str,
) -> None:
    """A dp prop states its default or refuses to render; it never guesses."""
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    edit(registry)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match=message):
        main.load_registry()


def test_a_payloadless_callback_dispatches_the_bare_action() -> None:
    """``onClick`` takes nothing, so there is nothing to report."""
    block = render("Button", components()["Button"])
    assert "onClick = { context.actions.dispatch(model.props.onClick) }" in block


def test_a_callback_with_a_payload_reports_it() -> None:
    """``onCheckedChange`` hands back the new value and must report it.

    Omitting the payload compiles and then does nothing: the app never learns
    the checkbox moved. Passing a ``String`` where a ``Boolean`` belongs does not
    compile at all. Both failures trace back to the same missing declaration.
    """
    block = render("Checkbox", components()["Checkbox"])
    assert (
        "onCheckedChange = { value -> "
        "context.event(model.props.onCheckedChange, JsonPrimitive(value)) }" in block
    )


def test_a_payload_type_the_generator_cannot_map_is_refused() -> None:
    """Rather than guess, decline."""
    entry = components()["Checkbox"]
    entry["props"]["onCheckedChange"]["payload"] = [{"name": "value", "type": "color"}]
    assert render("Checkbox", entry) == ""


@pytest.mark.parametrize(
    ("prop", "why"),
    [
        ({"type": "actionId", "content": {"composable": "Text"}}, "slots flatten text"),
        (
            {"type": "string", "payload": [{"name": "value", "type": "boolean"}]},
            "only callbacks carry payloads",
        ),
        ({"type": "string", "content": {"composable": ""}}, "needs a composable"),
        (
            {"type": "actionId", "payload": [{"name": "", "type": "boolean"}]},
            "payload fields need names",
        ),
        (
            {
                "type": "actionId",
                "payload": [
                    {"name": "value", "type": "boolean"},
                    {"name": "value", "type": "string"},
                ],
            },
            "payload field names must be unique",
        ),
    ],
)
def test_the_registry_refuses_an_impossible_prop(prop: dict, why: str) -> None:
    """A prop that cannot exist is refused at parse time, not at build time."""
    from pycompose.errors import ComponentRegistryError
    from pycompose.model.catalog.registry import PropDef

    try:
        PropDef.from_mapping(prop, where="test")
    except ComponentRegistryError:
        return
    pytest.fail(f"{prop} was accepted, but {why}")


def test_the_generated_file_imports_only_what_it_uses() -> None:
    """A wildcard or a stale import is the kind of thing spotless fixes silently."""
    source = GENERATED.read_text()
    body = source.split("object GeneratedAdapters", 1)[1]
    for line in source.splitlines():
        if line.startswith("import "):
            # An aliased import ends in "as Alias", and it is the alias the body
            # has to use, not the class name.
            simple = (
                line.rsplit(" as ", 1)[-1]
                if " as " in line
                else line.rsplit(".", 1)[-1]
            )
            assert re.search(rf"\b{re.escape(simple)}\b", body), f"unused: {line}"


def test_every_enum_color_and_resource_prop_names_how_it_resolves() -> None:
    """A named constant or a colour resolves through its value family.

    Declared per prop, never inferred from the value set: two families may
    share a value set, and the failure would be a wrong alignment rather than an
    error. A resource names its loader. A state-held prop never reaches a
    native parameter, so it needs neither.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        held = held_props(entry)
        for prop, spec in entry["props"].items():
            if prop in held:
                continue
            if spec["type"] in {"enum", "color"}:
                assert "valueType" in spec, f"{name}.{prop}"
                assert "decode" not in spec, f"{name}.{prop}"
            if spec["type"] == "resource":
                assert spec.get("decode"), f"{name}.{prop} has no loader"


def named_example(style: dict[str, Any]) -> str:
    """Render a minimal generated entry carrying a named-constant prop.

    Text is hand-written by design, so a minimal entry is rendered for real and
    the assertion covers the generator's own emission.

    Args:
        style: The ``style`` prop's schema entry.

    Returns:
        The rendered adapter, empty when the entry is not generated.
    """
    entry = {
        "children": {"allowed": False},
        "props": {"style": style, "text": {"type": "string", "required": True}},
    }
    return render("Text", entry)


def test_a_named_constant_resolves_its_tag_or_takes_the_native_default() -> None:
    """``textStyle`` reads MaterialTheme, so it binds to a local in composition."""
    default = "androidx.compose.material3.MaterialTheme.typography.bodyMedium"
    block = named_example(
        {
            "type": "enum",
            "valueType": "TextStyle",
            "values": ["bodyLarge", "bodyMedium"],
            "default": "bodyMedium",
            "nativeDefault": default,
        }
    )
    assert (
        "val styleValue = model.props.style?.let { "
        "com.pycompose.renderer.generated.ValueResolver.textStyle(it).getOrThrow() }"
        f" ?: {default}"
    ) in block
    assert "style = styleValue" in block


def test_an_optional_named_constant_needs_a_native_default() -> None:
    """Absent, the parameter must take something; nothing is guessed."""
    style = {"type": "enum", "valueType": "TextStyle", "values": ["bodyLarge"]}
    assert named_example(style) == ""


def test_a_resource_prop_needs_a_wrapper() -> None:
    """A resource loads off the Compose thread, which no generated call does.

    ADR-0005's degrade-don't-throw rule is the wrapper's job (ResourceImage,
    ResourceText), so an entry with a resource prop and no wrapper is not
    generated rather than generated to block or throw.
    """
    from pycompose_codegen.emit.adapters.assemble import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "painter": {
                "type": "resource",
                "values": ["drawable"],
                "decode": "resourceImage",
                "required": True,
            }
        },
    }
    assert render_one("Icon", entry) == ""


def test_a_wrapped_component_is_not_reduced_to_resolved_values() -> None:
    """Text loads off the Compose thread; a String? cannot express that."""
    for name in ("Text", "Image"):
        entry = components()[name]
        assert entry.get("wrapper"), f"{name} should declare a wrapper"
        assert render(name, entry) == "", f"{name} must not be generated"


def test_the_registry_refuses_a_decoder_on_a_type_that_needs_none() -> None:
    """A decode on a plain string is a category error, not a harmless extra."""
    from pycompose.errors import ComponentRegistryError
    from pycompose.model.catalog.registry import PropDef

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "string", "decode": "color"}, where="test")


def test_the_registry_refuses_an_unknown_decoder() -> None:
    from pycompose.errors import ComponentRegistryError
    from pycompose.model.catalog.registry import PropDef

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "enum", "decode": "diagonal"}, where="test")


def test_an_index_prop_is_guarded_by_the_items_it_indexes() -> None:
    """Compose throws outside its items; the adapter clamps or composes nothing."""
    from pycompose_codegen.emit.adapters.assemble import render as render_one
    from pycompose_codegen.emit.adapters.imports import extra_imports

    entry = components()["PrimaryTabRow"]
    block = render_one("PrimaryTabRow", entry)
    assert (
        "val selectedTabIndexValue = context.index(model.props.selectedTabIndex, "
        'model.children.inSlot("tabs"), node.id)'
    ) in block
    assert "if (selectedTabIndexValue != null) {" in block
    assert "selectedTabIndex = selectedTabIndexValue," in block
    assert {"com.pycompose.renderer.index", "com.pycompose.renderer.inSlot"} <= (
        extra_imports(entry)
    )


@pytest.mark.parametrize(
    "change",
    [{"type": "string", "indexOf": "tabs"}, {"type": "integer", "indexOf": "rows"}],
)
def test_an_index_must_be_an_integer_naming_a_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, str]
) -> None:
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["PrimaryTabRow"]["props"]["selectedTabIndex"] = change
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="'indexOf' must be an integer naming a slot"):
        main.load_registry()


def test_an_optional_callback_reaches_nobody_when_unbound() -> None:
    """A nullable action id must not reach dispatch, which takes a String."""
    from pycompose_codegen.emit.adapters.assemble import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "onDone": {"type": "actionId"},
            "onMove": {
                "type": "actionId",
                "payload": [{"name": "value", "type": "number"}],
            },
            "value": {"type": "number", "nativeType": "Float", "required": True},
        },
    }
    block = render_one("Slider", entry)
    assert (
        "onDone = { model.props.onDone?.let { context.actions.dispatch(it) } }" in block
    )
    assert (
        "onMove = { value -> model.props.onMove?.let "
        "{ context.event(it, JsonPrimitive(value)) } }"
    ) in block
    # The wire carries a double; Compose takes a Float.
    assert "value = model.props.value.toFloat()" in block
