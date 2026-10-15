"""Tests for Kotlin adapter generation.

The generator's job is to emit code that compiles, and its failure mode is
generating code that nearly does. Each test below pins one way that happened, so
the next schema change that reintroduces it fails here rather than at
``./gradlew :host:compileDebugKotlin``.

``tools/`` is importable thanks to ``tests/conftest.py``.
"""

from __future__ import annotations

import json
import pathlib
import re
from pathlib import Path
from typing import Any

import pytest

from pycompose.schema.codegen.adapters import (
    composables,
    is_mechanical,
    render,
    render_file,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "components.json"
GENERATED = (
    Path(__file__).resolve().parent.parent
    / "android/host/src/main/kotlin/com/pycompose/host/ui/GeneratedAdapters.kt"
)
MANUAL = (
    Path(__file__).resolve().parent.parent
    / "android/host/src/main/kotlin/com/pycompose/host/ui/BuiltinComponents.kt"
)


def components() -> dict[str, Any]:
    """Return the schema's component entries, keyed by name.

    Returns:
        Every component entry in ``components.json``.
    """
    return json.loads(SCHEMA_PATH.read_text())["components"]


# ---------------------------------------------------------------------------
# The marker decides, and the marker is honoured
# ---------------------------------------------------------------------------


def test_a_component_marked_manual_generates_nothing() -> None:
    """``adapter: manual`` must be load-bearing, not decoration."""
    registry = components()
    marked = [n for n, e in registry.items() if e.get("adapter") == "manual"]
    assert marked, "expected some components to be manual"
    for name in marked:
        assert not is_mechanical(registry[name]), f"{name} is marked manual"
        assert render(name, registry[name]) == "", f"{name} generated an adapter"


def manual_reason(entry: dict[str, Any]) -> str | None:
    """Why a component cannot be derived, or None if it can.

    Args:
        entry: The component's schema entry.

    Returns:
        A short reason, or None when the adapter is derivable.
    """
    if entry.get("adapter") == "manual":
        return "marked manual"
    if entry.get("wrapper"):
        return f"delegates to {entry['wrapper']}"
    if entry.get("children", {}).get("allowed"):
        return "composes children"
    undecodable = [
        name
        for name, spec in entry.get("props", {}).items()
        if spec.get("type") in {"enum", "color", "resource"} and not spec.get("decode")
    ]
    if undecodable:
        return f"undecoded props: {', '.join(sorted(undecodable))}"
    return None


def test_every_component_is_either_generated_or_has_a_stated_reason() -> None:
    """No component may fall through both paths unnoticed.

    This is the gap that produced a blank screen once: a component in neither
    file, discovered by a user rather than by a test. The reason has to be
    *stated* rather than merely detectable, so that reading the schema tells you
    why a component is hand-written.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        reason = manual_reason(entry)
        if reason is None:
            assert render(name, entry), f"{name} is derivable but rendered nothing"
        else:
            assert render(name, entry) == "", f"{name} manual ({reason}) but generated"


def test_a_component_excluded_only_by_a_rule_still_says_so() -> None:
    """`adapter: manual` is the fallback, not the only way to be manual.

    A component excluded purely by a rule the generator applies is still
    hand-written, and the schema should record that -- otherwise someone tidying
    the schema has no idea Box's adapter is theirs to maintain.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        if entry.get("children", {}).get("allowed"):
            assert (
                entry.get("adapter") == "manual"
            ), f"{name} composes children but is not marked manual"


def test_the_committed_file_matches_what_the_generator_produces() -> None:
    """Generated Kotlin is a build artifact; drift is a failed --check."""
    assert GENERATED.exists(), "gen.py did not emit GeneratedAdapters.kt"
    committed = GENERATED.read_text()
    assert (
        render_file({"components": components()}).strip() == committed.strip()
    ), "GeneratedAdapters.kt is stale; run python tools/schema/gen.py"


def test_each_component_is_registered_exactly_once_across_both_files() -> None:
    """No duplicates, no omissions: one adapter per component, in one file."""
    registry = components()
    # No leading dot: TextField's adapter opens a helper, so its register call
    # starts a statement rather than continuing a chain.
    pattern = r'register\("(\w+)"'
    generated_names = re.findall(pattern, GENERATED.read_text())
    manual_names = re.findall(pattern, MANUAL.read_text())

    assert len(generated_names) == len(set(generated_names)), "duplicate in generated"
    assert len(manual_names) == len(set(manual_names)), "duplicate in manual"

    both = set(generated_names) & set(manual_names)
    assert not both, f"registered twice: {sorted(both)}"

    covered = set(generated_names) | set(manual_names)
    assert covered == set(registry), (
        f"uncovered: {sorted(set(registry) - covered)}; "
        f"unknown: {sorted(covered - set(registry))}"
    )


# ---------------------------------------------------------------------------
# Nullability: the mistake that produced "does not compile"
# ---------------------------------------------------------------------------


def test_no_optional_prop_is_passed_through() -> None:
    """A nullable Kotlin property must never reach Compose as a non-null.

    ``Boolean?`` into a ``Boolean`` parameter does not compile. A prop may only
    be passed when the schema marks it required or gives it a default; anything
    else is omitted so Compose's own default applies.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        block = render(name, entry)
        if not block:
            continue
        for prop, spec in entry["props"].items():
            referenced = re.search(rf"model\.props\.{re.escape(prop)}\b", block)
            if referenced is None:
                continue
            if spec["type"] in ("actionId", "modifier") or spec.get("content"):
                continue
            assert (
                spec.get("required") or "default" in spec or "nativeDefault" in spec
            ), (
                f"{name}.{prop} is optional and has no default, "
                "so the generated model types it nullable"
            )


def test_an_omitted_optional_prop_is_simply_absent() -> None:
    """A prop with a default is passed; one without is left to Compose."""
    block = render("Button", components()["Button"])
    assert "enabled = model.props.enabled" in block

    # TextButton carries no optional-without-default scalar to omit, so assert
    # the rule on a prop that has one instead.
    block = render("FilterChip", components()["FilterChip"])
    for prop, spec in components()["FilterChip"]["props"].items():
        if not spec.get("required") and "default" not in spec:
            assert f"model.props.{prop}" not in block


# ---------------------------------------------------------------------------
# Content slots: Compose has no Button.text
# ---------------------------------------------------------------------------


def test_a_flattened_slot_renders_its_declared_composable() -> None:
    """``Button`` has no ``text`` parameter; text is a content lambda."""
    block = render("Button", components()["Button"])
    assert "Text(model.props.text)" in block
    assert "text = model.props.text" not in block
    # Trailing lambda, because Button takes content positionally.
    # A trailing lambda, because Button takes its content positionally.
    assert ") {\n                    Text(model.props.text)\n            }" in block


def test_a_named_slot_is_passed_by_name() -> None:
    """``FilterChip`` names its slot ``label``, so it is an argument, not trailing."""
    block = render("FilterChip", components()["FilterChip"])
    assert "label = { Text(model.props.label) }" in block


def test_a_slot_declares_the_import_its_content_needs() -> None:
    """``Button`` does not compile without ``Text`` in scope."""
    assert "Text" in composables("Button", components()["Button"])
    # The component's own name is not an extra import of itself.
    assert "Button" not in composables("Button", components()["Button"])


def test_an_optional_slot_is_not_generated() -> None:
    """``TextField.label`` is optional, so it needs a null check -- a decision."""
    entry = components()["TextField"]
    assert entry["props"]["label"].get("content")
    assert render("TextField", entry) == ""


# ---------------------------------------------------------------------------
# Callback arity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The schema rejects nonsense
# ---------------------------------------------------------------------------


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
    from pycompose.core.registry_types import PropDef
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


# ---------------------------------------------------------------------------
# Decoders: the prop types whose wire form is not their Kotlin type
# ---------------------------------------------------------------------------


def test_every_enum_color_and_resource_prop_declares_its_decoder() -> None:
    """Without a `decode`, a generator cannot tell one enum family from another.

    `PropResolver` knows how to turn `"start"` into an `Alignment.Horizontal`,
    but nothing in the data says `["start","center","end"]` means *horizontal*
    rather than some other family with the same three values. Declared per prop,
    never inferred from the value set: inference breaks silently the day two
    families share a value set, and the failure is a wrong alignment rather than
    an error.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        for prop, spec in entry["props"].items():
            if spec["type"] in {"enum", "color", "resource"}:
                assert spec.get(
                    "decode"
                ), f"{name}.{prop} is a {spec['type']} with no decoder"


def test_a_decoder_binds_to_a_resolver_that_exists() -> None:
    """A typo'd decoder name generates Kotlin that does not compile."""
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
    # Everything except the resource family resolves through PropResolver.
    for decoder in declared - {"resourceText", "resourceImage", "resourceFont"}:
        source = (
            pathlib.Path("android/renderer/src/main/kotlin")
            / "com/pycompose/renderer/PropResolver.kt"
        ).read_text()
        assert f"fun {decoder}(" in source, f"{decoder} has no resolver"


def decoded_example() -> tuple[str, str]:
    """Return a component that is generated and carries a decoded prop.

    Text and Image both declare `wrapper` and so are hand-written by design;
    testing decoded output through them would assert nothing about the
    generator. Scaffold is excluded by children, so this builds a minimal
    component instead and renders it for real.

    Returns:
        The component name and its rendered adapter.
    """
    from pycompose.schema.codegen.adapters import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "resource": {
                "type": "resource",
                "values": ["drawable", "asset"],
                "decode": "resourceImage",
                "required": True,
            },
            "contentDescription": {"type": "string"},
        },
    }
    return "Image", render_one("Image", entry)


def test_a_decoded_prop_becomes_a_local_not_an_inline_call() -> None:
    """`textStyle` reads MaterialTheme, which is only in scope in composition.

    Inlining it into an argument list makes the call non-composable, which the
    compiler rejects -- so decoded props bind to a `val` first.
    """
    name, block = decoded_example()
    assert block, f"{name} should render"
    assert "val resourceValue: Painter? = resources?.image(" in block
    assert "resource = resourceValue" in block


def test_a_bad_resource_degrades_rather_than_throwing() -> None:
    """ADR-0005: Compose must never see an exception from a malformed prop."""
    _, block = decoded_example()
    assert ".getOrNull()" in block


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
    from pycompose.core.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "string", "decode": "color"}, where="test")


def test_the_registry_refuses_an_unknown_decoder() -> None:
    from pycompose.core.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "enum", "decode": "diagonal"}, where="test")
