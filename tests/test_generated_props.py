"""Prop passing: scalars, dp, callbacks, decoders and import hygiene."""

from __future__ import annotations

import json
import pathlib
import re
from pathlib import Path
from typing import Any

import pytest
from test_generated_adapters import (
    GENERATED,
    SCHEMA_PATH,
    components,
)

from pycompose.schema.codegen.adapter_helpers import _held_props
from pycompose.schema.codegen.adapters import (
    render,
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
            "'nativeDefault' is read only for value and dp props",
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
    from pycompose.schema.codegen import main, rules

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
    from pycompose.contract.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

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


def test_every_enum_color_and_resource_prop_declares_its_decoder() -> None:
    """Without a `decode`, a generator cannot tell one enum family from another.

    `PropResolver` knows how to turn `"start"` into an `Alignment.Horizontal`,
    but nothing in the data says `["start","center","end"]` means *horizontal*
    rather than some other family with the same three values. Declared per prop,
    never inferred from the value set: inference breaks silently the day two
    families share a value set, and the failure is a wrong alignment rather than
    an error. A state-held prop never reaches a native parameter, so the adapter
    resolves it through its holder instead and needs no decoder.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        held = _held_props(entry)
        for prop, spec in entry["props"].items():
            if prop in held:
                continue
            if spec["type"] in {"enum", "color", "resource"}:
                assert spec.get(
                    "decode"
                ), f"{name}.{prop} is a {spec['type']} with no decoder"


def test_a_decoder_binds_to_a_resolver_that_exists() -> None:
    """A typo'd decoder name generates Kotlin that does not compile."""
    from pycompose.schema.codegen.adapter_helpers import RESOLVER_OWNER
    from pycompose.schema.codegen.adapters import RESOLVER_FALLBACK, RESOLVER_RETURN

    declared = {
        spec["decode"]
        for entry in components().values()
        for spec in entry["props"].values()
        if spec.get("decode")
    }
    assert declared, "expected the catalog to declare decoders"
    for decoder in declared:
        assert decoder in RESOLVER_RETURN, decoder
        assert decoder in RESOLVER_FALLBACK, decoder
    # Non-resource decoders must exist on their declared native resolver.
    for decoder in declared - {"resourceText", "resourceImage", "resourceFont"}:
        source = (
            pathlib.Path("android/renderer/src/main/kotlin")
            / "com/pycompose/renderer/PropResolver.kt"
        ).read_text()
        assert f"fun {decoder}(" in source, f"{decoder} has no resolver"
        assert f"object {RESOLVER_OWNER.get(decoder, 'PropResolver')}" in source


def test_tooltip_position_uses_its_native_decoder() -> None:
    """Experimental positions have a declared resolver, never a guessed alignment."""
    from pycompose.schema.codegen.adapters import render

    entry = {
        "props": {"position": components()["TooltipBox"]["props"]["position"]},
        "children": {"allowed": False},
    }
    adapter = render("Tooltip", entry)
    assert "com.pycompose.renderer.TooltipPropResolver.tooltipPosition(" in adapter
    assert "androidx.compose.material3.TooltipAnchorPosition.Above" in adapter


def decoded_example() -> tuple[str, str]:
    """Return a component that is generated and carries a decoded prop.

    Text and Image both declare `wrapper` and so are hand-written by design;
    testing decoded output through them would assert nothing about the
    generator. A minimal entry is rendered for real instead, so the assertion
    covers the generator's own emission rather than a hand-written adapter.

    Returns:
        The component name and its rendered adapter.
    """
    from pycompose.schema.codegen.adapters import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "style": {
                "type": "enum",
                "values": ["bodyLarge", "bodyMedium"],
                "decode": "textStyle",
                "default": "bodyMedium",
            },
            "text": {"type": "string", "required": True},
        },
    }
    return "Text", render_one("Text", entry)


def test_a_decoded_prop_becomes_a_local_not_an_inline_call() -> None:
    """`textStyle` reads MaterialTheme, which is only in scope in composition.

    Inlining it into an argument list makes the call non-composable, which the
    compiler rejects -- so decoded props bind to a `val` first.
    """
    name, block = decoded_example()
    assert block, f"{name} should render"
    assert "val styleValue: androidx.compose.ui.text.TextStyle = " in block
    assert "style = styleValue" in block


def test_a_resource_prop_needs_a_wrapper() -> None:
    """A resource loads off the Compose thread, which no generated call does.

    ADR-0005's degrade-don't-throw rule is the wrapper's job (ResourceImage,
    ResourceText), so an entry with a resource prop and no wrapper is not
    generated rather than generated to block or throw.
    """
    from pycompose.schema.codegen.adapters import render as render_one

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


def test_an_optional_decoded_prop_is_not_passed_to_a_non_null_resolver() -> None:
    """`PropResolver.color` takes a String; a nullable would not compile."""
    from pycompose.schema.codegen.adapters import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "text": {"type": "string", "required": True},
            "color": {"type": "color", "decode": "color"},
        },
    }
    block = render_one("Text", entry)
    assert "model.props.color?.takeIf" in block


def test_a_wrapped_component_is_not_reduced_to_resolved_values() -> None:
    """Text loads off the Compose thread; a String? cannot express that."""
    for name in ("Text", "Image"):
        entry = components()[name]
        assert entry.get("wrapper"), f"{name} should declare a wrapper"
        assert render(name, entry) == "", f"{name} must not be generated"


def test_the_registry_refuses_a_decoder_on_a_type_that_needs_none() -> None:
    """A decode on a plain string is a category error, not a harmless extra."""
    from pycompose.contract.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "string", "decode": "color"}, where="test")


def test_the_registry_refuses_an_unknown_decoder() -> None:
    from pycompose.contract.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "enum", "decode": "diagonal"}, where="test")


def test_an_index_prop_is_guarded_by_the_items_it_indexes() -> None:
    """Compose throws outside its items; the adapter clamps or composes nothing."""
    from pycompose.schema.codegen.adapters import extra_imports
    from pycompose.schema.codegen.adapters import render as render_one

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
    from pycompose.schema.codegen import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["PrimaryTabRow"]["props"]["selectedTabIndex"] = change
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="'indexOf' must be an integer naming a slot"):
        main.load_registry()


def test_an_optional_callback_reaches_nobody_when_unbound() -> None:
    """A nullable action id must not reach dispatch, which takes a String."""
    from pycompose.schema.codegen.adapters import render as render_one

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
