"""Tests for Kotlin adapter generation.

The generator's job is to emit code that compiles, and its failure mode is
generating code that nearly does. Each test below pins one way that happened, so
the next schema change that reintroduces it fails here rather than at
``./gradlew :host:compileDebugKotlin``.

``tools/`` is importable thanks to ``tests/conftest.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from schema.gen_adapters import composables, is_mechanical, render, render_file

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


def test_every_component_is_either_marked_manual_or_generated() -> None:
    """No component may fall through both paths unnoticed.

    This is the gap that produced a blank screen once: a component in neither
    file, discovered by a user rather than by a test.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        manual = entry.get("adapter") == "manual"
        generated = bool(render(name, entry))
        why = (
            "marked manual but still generated"
            if manual
            else "neither marked manual nor generated"
        )
        assert manual != generated, f"{name} is {why}"


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
            assert spec.get("required") or "default" in spec, (
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
