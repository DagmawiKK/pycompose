"""The host-created interaction source: press state returns as an action.

A component that accepts a host-created interaction source names, in its schema
entry, the native parameter the source fills and the prop whose action observes
press state. The source belongs to the host -- one per node id -- so pulling a
new snapshot restarts no ripple in flight; the reaction a user sees stays the
component's own, and the app learns about the press a frame later.

These tests pin the Python half of that contract: how the observation reaches
the wire, how the adapter fills the parameter, and what the codegen refuses
rather than guesses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pycompose.core.node import Node
from pycompose.ir import emit_ir, to_dict, validate_ir
from pycompose.m3 import Button
from pycompose.schema.codegen.adapters import render
from pycompose.state import State

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "components.json"


def snapshot(root: Node) -> dict:
    """Emit, validate and serialize one root.

    Args:
        root: The tree to publish.

    Returns:
        The canonical wire snapshot.
    """
    candidate = emit_ir(State(root=root), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    return to_dict(candidate)


def components() -> dict[str, Any]:
    """Return the schema's component entries, keyed by name.

    Returns:
        Every component entry in ``components.json``.
    """
    return json.loads(SCHEMA_PATH.read_text())["components"]


def test_the_generated_constructor_observes_press() -> None:
    """``on_press`` is a prop; the wire carries it camelCase like every other."""
    wire = snapshot(Button(id="ok", text="OK", on_click="increment", on_press="submit"))
    assert wire["root"]["props"]["onPress"] == "submit"


def test_press_observation_is_absent_until_declared() -> None:
    """A node that observes nothing carries no interaction prop at all."""
    wire = snapshot(Button(id="ok", text="OK", on_click="increment"))
    assert "onPress" not in wire["root"]["props"]


def test_every_declared_source_observes_a_prop_it_owns() -> None:
    """The declaration names a real actionId prop, so the host never guesses."""
    for name, entry in sorted(components().items()):
        interaction = entry.get("interaction")
        if interaction is None:
            continue
        prop = entry["props"][interaction["prop"]]
        assert prop["type"] == "actionId", name
        payload = prop["payload"]
        assert [field["type"] for field in payload] == ["boolean"], name


# ---------------------------------------------------------------------------
# The adapter fills the parameter; the observed prop is not a native one
# ---------------------------------------------------------------------------


def test_the_adapter_passes_the_host_source_where_the_schema_says() -> None:
    """The observed prop is not a native parameter; the source fills its place."""
    adapter = render("Button", components()["Button"])
    assert (
        "val interactionSourceValue = context.interactionSource("
        "model.id, model.props.onPress)" in adapter
    )
    assert "interactionSource = interactionSourceValue" in adapter
    assert "onPress =" not in adapter


def test_a_component_without_a_source_gets_no_interaction_local() -> None:
    """Only components that declare a source ask the renderer for one."""
    adapter = render("Column", components()["Column"])
    assert "interactionSource" not in adapter
    assert "interactionSourceValue" not in adapter


# ---------------------------------------------------------------------------
# The codegen refuses an interaction it cannot render faithfully
# ---------------------------------------------------------------------------


def _load_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """Validate the catalog after one deliberate change.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.
        mutate: Applies the change to the loaded registry.
    """
    from pycompose.schema.codegen import main

    registry = json.loads(SCHEMA_PATH.read_text())
    mutate(registry)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    main.load_registry()


def _interaction(registry: dict[str, Any], component: str) -> dict[str, Any]:
    """Return one mutably loaded interaction entry.

    Args:
        registry: The loaded catalog.
        component: Component owning the interaction.

    Returns:
        The interaction's raw entry, for the caller to break.
    """
    return registry["components"][component]["interaction"]


def _press(registry: dict[str, Any], component: str) -> dict[str, Any]:
    """Return the observing prop's payload field.

    Args:
        registry: The loaded catalog.
        component: Component owning the interaction.

    Returns:
        The payload field, for the caller to break.
    """
    prop = _interaction(registry, component)["prop"]
    return registry["components"][component]["props"][prop]["payload"][0]


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda registry: _interaction(registry, "Button").update(unknown=True),
            "unknown keys",
        ),
        (
            lambda registry: _interaction(registry, "Button").update(native="text"),
            "repeats another parameter",
        ),
        (
            lambda registry: _interaction(registry, "FilterChip").update(
                native="leadingIcon"
            ),
            "repeats another parameter",
        ),
        (
            lambda registry: _interaction(registry, "Button").update(prop="onHold"),
            "must name one of the component's props",
        ),
        (
            lambda registry: _interaction(registry, "Button").update(prop="text"),
            "must be an actionId",
        ),
        (
            lambda registry: _press(registry, "Button").update(type="string"),
            "needs one boolean payload field",
        ),
        (
            lambda registry: _press(registry, "Button").update(name="Value"),
            "needs one boolean payload field",
        ),
    ],
)
def test_the_codegen_refuses_an_unrenderable_interaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_it: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """An interaction the generator cannot fill faithfully is refused, not guessed.

    An adapter emitted from a half-understood declaration compiles and then
    drops the observation silently, which is worse than not building at all.
    """
    with pytest.raises(SystemExit, match=expected):
        _load_with(tmp_path, monkeypatch, break_it)


def test_the_codegen_refuses_a_second_payload_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One boolean is the whole observation; two fields would mean the host guesses."""
    with pytest.raises(SystemExit, match="needs one boolean payload field"):
        _load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["Button"]["props"]["onPress"][
                "payload"
            ].append({"name": "extra", "type": "boolean"}),
        )


# ---------------------------------------------------------------------------
# The runtime registry carries the declaration, not just the codegen
# ---------------------------------------------------------------------------


def test_the_runtime_registry_round_trips_the_interaction() -> None:
    """The registry type keeps the declaration a schema reader can trust."""
    from pycompose.core.registry_types import ComponentSpec
    from pycompose.errors import ComponentRegistryError

    spec = ComponentSpec.from_mapping(
        "Button",
        {
            "category": "buttons",
            "stability": "stable",
            "props": {},
            "children": {"allowed": False},
            "interaction": {"native": "interactionSource", "prop": "onPress"},
        },
    )
    assert spec.interaction is not None
    assert spec.to_mapping()["interaction"] == {
        "native": "interactionSource",
        "prop": "onPress",
    }
    with pytest.raises(ComponentRegistryError, match="'native' must be a name"):
        ComponentSpec.from_mapping(
            "Button",
            {
                "category": "buttons",
                "stability": "stable",
                "props": {},
                "children": {"allowed": False},
                "interaction": {"native": 3},
            },
        )
