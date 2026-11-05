"""Bound props: every prop the pin can animate is read through its converter.

The generator owns no list of animatable types. The pin declares a
``TwoWayConverter`` per type Compose can animate, the lock records on each prop
the Kotlin type it would be animated as, and this test walks the lock: each of
those props must render one state, at the phase the call site is read in, with
the converter the pin names for its type. A prop added to the catalog is covered
the moment it derives, and a prop that stops deriving fails here.

The props no generated adapter carries are read by a hand-written one, which
goes through the same readers (``boundDp``, ``boundColor``, ``bound``,
``bindingState``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pycompose_codegen.emit.adapters.assemble import render
from pycompose_codegen.emit.adapters.policy import camel

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"
MANUAL_DIR = (
    Path(__file__).resolve().parents[4]
    / "android/host/src/main/kotlin/com/pycompose/host/ui"
)
GENERATED = MANUAL_DIR / "GeneratedAdapters.kt"

"""Where a component reads its props: the call itself, while composing."""

READERS = (
    "boundDp(",
    "boundColor(",
    "bound(",
    "bindingState(",
    "optionalBindingState(",
)
"""The host functions that read a prop the app may bind."""

DISCOVERY_FLOOR = 100
"""Below this, the walk is not finding the catalog: fail rather than pass empty."""


def lock() -> dict[str, Any]:
    """Return the parsed catalog lock.

    Returns:
        The lock, as written by the derivation.
    """
    return json.loads(SCHEMA_PATH.read_text())


def animatable() -> list[tuple[str, str, dict[str, Any]]]:
    """Every ``(component, prop, spec)`` the pin gives a converter.

    Returns:
        The pairs, in catalog order.
    """
    return [
        (name, prop, spec)
        for name, entry in lock()["components"].items()
        for prop, spec in entry["props"].items()
        if "animation" in spec
    ]


def manual_sources() -> list[str]:
    """Read every hand-written adapter, excluding the generated registry.

    Returns:
        Each file's lines, for a windowed search.
    """
    return [
        line
        for path in sorted(MANUAL_DIR.glob("*.kt"))
        if path != GENERATED
        for line in path.read_text().split("\n")
    ]


def test_every_bindable_prop_of_a_generated_component_reads_through_it() -> None:
    """One read per bindable prop, through the pin's converter.

    A prop read in the call is one helper call; one read later -- by a
    provider, or through an index clamp -- keeps a state declared for its phase.
    """
    converters = lock()["converters"]
    pairs = [
        (name, prop, spec)
        for name, prop, spec in animatable()
        if render(name, lock()["components"][name])
    ]
    assert len(pairs) >= DISCOVERY_FLOOR, f"only {len(pairs)} generated pairs found"
    for name, prop, spec in pairs:
        block = render(name, lock()["components"][name])
        expression = converters[spec["animation"]]["expression"]
        if "provider" in spec or "indexOf" in spec:
            assert f"val {camel(prop)}State =" in block, f"{name}.{prop} keeps no state"
        else:
            read = f"val {camel(prop)}Value = "
            line = next((x for x in block.splitlines() if read in x), "")
            assert (
                expression in line
            ), f"{name}.{prop} is not one read through its converter"
        assert expression in block, f"{name}.{prop} does not use its pin's converter"


def test_a_prop_the_pin_gives_no_converter_is_passed_as_a_plain_value() -> None:
    """A string has no converter, so its adapter reads it and makes no state."""
    entry = lock()["components"]["Button"]
    block = render("Button", entry)
    plain = [
        prop
        for prop, spec in entry["props"].items()
        if "animation" not in spec and spec["type"] in {"string", "boolean"}
    ]
    assert plain, "Button has no plain scalar prop to pin"
    for prop in plain:
        assert f"val {camel(prop)}State" not in block


def test_a_hand_written_adapter_reads_its_bindable_props_through_a_state() -> None:
    """The props no generated adapter carries go through the same readers."""
    sources = manual_sources()
    pairs = [
        (name, prop)
        for name, prop, _spec in animatable()
        if not render(name, lock()["components"][name])
    ]
    assert pairs, "every bindable prop is generated: nothing to pin here"
    for name, prop in pairs:
        wanted = f"props.{camel(prop)}"
        window = [
            sources[index + offset]
            for index, line in enumerate(sources)
            if wanted in line
            for offset in (-1, 0)
            if 0 <= index + offset < len(sources)
        ]
        assert any(
            reader in line for line in window for reader in READERS
        ), f"{name}.{prop} is read without a binding-aware reader"
