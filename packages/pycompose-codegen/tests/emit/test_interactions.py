"""The host-created interaction source: session state returns as an action.

A component that accepts a host-created interaction source names, in its schema
entry, the native parameter the source fills and one actionId prop per observed
interaction kind. The source belongs to the host -- one per node id -- so pulling
a new snapshot restarts no interaction in flight; the reaction a user sees stays
the component's own, and the app learns about the interaction a frame later.

These tests pin the Python half of that contract: how observations reach the
wire, how the adapter fills the parameter, and what the codegen refuses rather
than guesses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pycompose_codegen.emit.adapters.assemble import render

from pycompose.material3 import Button
from pycompose.model.nodes.node import Node
from pycompose.model.snapshot import Snapshot
from pycompose.wire import emit_ir, to_dict, validate_ir

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"


def snapshot(root: Node) -> dict:
    """Emit, validate and serialize one root.

    Args:
        root: The tree to publish.

    Returns:
        The canonical wire snapshot.
    """
    candidate = emit_ir(Snapshot(root=root), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    return to_dict(candidate)


def components() -> dict[str, Any]:
    """Return the schema's component entries, keyed by name.

    Returns:
        Every component entry in the catalog lock.
    """
    return json.loads(SCHEMA_PATH.read_text())["components"]


def test_the_generated_constructor_observes_every_kind() -> None:
    """The observation props are ordinary props; the wire carries them camelCase."""
    wire = snapshot(
        Button(
            id="ok",
            text="OK",
            on_click="increment",
            on_press="submit",
            on_focus="submit",
            on_hover="submit",
        )
    )
    assert wire["root"]["props"]["onPress"] == "submit"
    assert wire["root"]["props"]["onFocus"] == "submit"
    assert wire["root"]["props"]["onHover"] == "submit"


def test_an_observation_is_absent_until_declared() -> None:
    """A node that observes nothing carries no interaction props at all."""
    wire = snapshot(Button(id="ok", text="OK", on_click="increment"))
    assert "onPress" not in wire["root"]["props"]
    assert "onFocus" not in wire["root"]["props"]
    assert "onHover" not in wire["root"]["props"]


def test_every_observation_names_a_prop_it_owns() -> None:
    """Each observation names a real actionId prop whose payload is one boolean."""
    for name, entry in sorted(components().items()):
        interaction = entry.get("interaction")
        if interaction is None:
            continue
        observations = interaction["observations"]
        assert observations, name
        for kind, observed in sorted(observations.items()):
            prop = entry["props"][observed]
            assert prop["type"] == "actionId", (name, kind)
            assert [field["type"] for field in prop["payload"]] == ["boolean"], (
                name,
                kind,
            )


def test_every_observed_kind_is_a_vocabulary_member() -> None:
    """The declaration never invents a kind the renderer cannot classify."""
    from pycompose.model.catalog.registry_types import INTERACTION_KINDS

    for name, entry in sorted(components().items()):
        interaction = entry.get("interaction")
        if interaction is None:
            continue
        assert set(interaction["observations"]) <= set(INTERACTION_KINDS), name


# ---------------------------------------------------------------------------
# The adapter fills the parameter; the observed props are not native ones
# ---------------------------------------------------------------------------


def test_the_adapter_passes_the_host_source_where_the_schema_says() -> None:
    """Observed props are not native parameters; the source fills their place."""
    adapter = render("Button", components()["Button"])
    assert "context.interactionSource(model.id, mapOf(" in adapter
    assert '"press" to model.props.onPress' in adapter
    assert '"focus" to model.props.onFocus' in adapter
    assert '"hover" to model.props.onHover' in adapter
    assert "interactionSource = interactionSourceValue" in adapter
    assert "onPress =" not in adapter
    assert "onFocus =" not in adapter
    assert "onHover =" not in adapter


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
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    mutate(registry)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
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


def _observations(registry: dict[str, Any], component: str) -> dict[str, str]:
    """Return one interaction's mutable observations map.

    Args:
        registry: The loaded catalog.
        component: Component owning the interaction.

    Returns:
        The observations map, for the caller to break.
    """
    return _interaction(registry, component)["observations"]


def _payload(registry: dict[str, Any], component: str, prop: str) -> dict[str, Any]:
    """Return one observed prop's payload field.

    Args:
        registry: The loaded catalog.
        component: Component owning the interaction.
        prop: The observed prop whose payload to break.

    Returns:
        The payload field, for the caller to break.
    """
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
            lambda registry: _interaction(registry, "Button").update(observations={}),
            "must be a non-empty object",
        ),
        (
            lambda registry: _observations(registry, "Button").update(hold="onPress"),
            "unknown observation",
        ),
        (
            lambda registry: _observations(registry, "Button").update(press="onHold"),
            "must name one of the props",
        ),
        (
            lambda registry: _observations(registry, "Button").update(press="text"),
            "must be an actionId",
        ),
        (
            lambda registry: _payload(registry, "Button", "onPress").update(
                type="string"
            ),
            "needs one boolean payload field",
        ),
        (
            lambda registry: _payload(registry, "Button", "onPress").update(
                name="Value"
            ),
            "needs one boolean payload field",
        ),
        (
            lambda registry: _payload(registry, "Button", "onFocus").update(
                name="Focus"
            ),
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
    from pycompose.errors import ComponentRegistryError
    from pycompose.model.catalog.registry_types import ComponentSpec

    spec = ComponentSpec.from_mapping(
        "Button",
        {
            "category": "buttons",
            "stability": "stable",
            "props": {},
            "children": {"allowed": False},
            "interaction": {
                "native": "interactionSource",
                "observations": {"press": "onPress", "hover": "onHover"},
            },
        },
    )
    assert spec.interaction is not None
    assert spec.to_mapping()["interaction"] == {
        "native": "interactionSource",
        "observations": {"press": "onPress", "hover": "onHover"},
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
    with pytest.raises(ComponentRegistryError, match="unknown observation"):
        ComponentSpec.from_mapping(
            "Button",
            {
                "category": "buttons",
                "stability": "stable",
                "props": {},
                "children": {"allowed": False},
                "interaction": {
                    "native": "interactionSource",
                    "observations": {"tap": "onPress"},
                },
            },
        )
