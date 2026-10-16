"""The host-owned state projection: Python states the value, the host drives it.

A component that needs native state -- a drawer's open/closed, a sheet's
expansion -- declares in its schema entry which native parameter the host's
remembered holder fills, which prop carries the app's desired value, and which
prop reports the settled value back as an action. The holder belongs to the
host and to one node id, so pulling a snapshot restarts no gesture in flight and
a change the app did not cause still reaches it.

These tests pin the Python half of that contract: how the desired value and its
report reach the wire, how the adapter fills the parameter, and what the codegen
refuses rather than guesses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pycompose.core.node import Node
from pycompose.ir import emit_ir, to_dict, validate_ir
from pycompose.m3 import ModalBottomSheet, ModalNavigationDrawer, Text
from pycompose.schema.codegen.adapters import render
from pycompose.state import State

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "components.json"

CATALOG = json.loads(SCHEMA_PATH.read_text())
"""The parsed catalog, so the wire tests state the version they are tested at."""

STATEFUL = "ModalNavigationDrawer"

GATED = "ModalBottomSheet"


def snapshot(root: Node) -> dict:
    """Emit, validate and serialize one root.

    Args:
        root: The tree to publish.

    Returns:
        The canonical wire snapshot.
    """
    candidate = emit_ir(State(root=root), CATALOG["schemaVersion"])
    assert validate_ir(candidate).snapshot is candidate
    return to_dict(candidate)


def components() -> dict[str, Any]:
    """Return the schema's component entries, keyed by name.

    Returns:
        Every component entry in ``components.json``.
    """
    return CATALOG["components"]


# ---------------------------------------------------------------------------
# The desired value and its report are ordinary props
# ---------------------------------------------------------------------------


def test_the_generated_constructor_states_the_desired_value() -> None:
    """The value and the report are props; the wire carries them camelCase."""
    wire = snapshot(
        ModalNavigationDrawer(
            id="drawer",
            open=True,
            on_open_change="submit",
            children=[Text(id="body", text="Body")],
            drawer=[Text(id="panel", text="Menu")],
        )
    )
    props = wire["root"]["props"]
    assert props["open"] is True
    assert props["onOpenChange"] == "submit"
    slots = {
        child["props"]["text"]: child.get("slot") for child in wire["root"]["children"]
    }
    assert slots == {"Body": None, "Menu": "drawer"}


def test_an_undeclared_desired_value_is_omitted_from_the_wire() -> None:
    """Absent is not false: the app said nothing, so nothing is reconciled."""
    wire = snapshot(
        ModalNavigationDrawer(id="drawer", on_open_change="submit", children=[])
    )
    assert "open" not in wire["root"]["props"]


def test_a_sheet_states_its_desired_value_and_reaches_its_handle_slot() -> None:
    """The same protocol on a modal surface, plus its own named slot."""
    wire = snapshot(
        ModalBottomSheet(
            id="sheet",
            open=True,
            on_open_change="submit",
            children=[Text(id="body", text="Body")],
            drag_handle=[Text(id="handle", text="Handle")],
        )
    )
    props = wire["root"]["props"]
    assert props["open"] is True
    assert props["onOpenChange"] == "submit"
    slots = {
        child["props"]["text"]: child.get("slot") for child in wire["root"]["children"]
    }
    assert slots == {"Body": None, "Handle": "dragHandle"}


# ---------------------------------------------------------------------------
# Every declaration agrees with the props it names
# ---------------------------------------------------------------------------


def test_every_declared_state_names_a_boolean_value_and_a_report() -> None:
    """The whole catalog's declarations hold, not just the enabled ones."""
    for name, entry in sorted(components().items()):
        state = entry.get("state")
        if state is None:
            continue
        props = entry["props"]
        assert state["native"] not in props, name
        value = props[state["value"]]
        assert value["type"] == "boolean", name
        assert not value.get("required"), name
        report = props[state["report"]]
        assert report["type"] == "actionId", name
        assert [field["type"] for field in report["payload"]] == ["boolean"], name
        # Neither is a native parameter of its own, so both are recorded as
        # reshaped rather than silently dropped.
        assert state["value"] in entry.get("reshaped", []), name
        assert state["report"] in entry.get("reshaped", []), name


def test_every_state_kind_is_a_vocabulary_member() -> None:
    """The declaration never invents a kind the host cannot create and drive."""
    from pycompose.core.registry_types import STATE_KINDS

    for name, entry in sorted(components().items()):
        state = entry.get("state")
        if state is not None:
            assert state["kind"] in STATE_KINDS, name


def test_every_declared_dismissal_names_an_unclaimed_parameter() -> None:
    """A completed callback is not a prop, and not anyone else's parameter."""
    for name, entry in sorted(components().items()):
        state = entry.get("state") or {}
        dismiss = state.get("dismiss")
        if dismiss is None:
            continue
        assert dismiss != state["native"], name
        assert dismiss not in entry["props"], name
        assert dismiss != entry["children"].get("native", "content"), name
        assert dismiss not in {
            slot["native"] for slot in entry.get("slots", {}).values()
        }, name


# ---------------------------------------------------------------------------
# The adapter fills the parameter; the props are not native ones
# ---------------------------------------------------------------------------


def test_the_adapter_passes_the_host_holder_where_the_schema_says() -> None:
    """The desired value and its report are not native parameters."""
    adapter = render(STATEFUL, components()[STATEFUL])
    assert (
        "val drawerStateValue = context.drawerState("
        "model.props.open, model.props.onOpenChange)" in adapter
    )
    assert "drawerState = drawerStateValue" in adapter
    assert "open =" not in adapter
    assert "onOpenChange =" not in adapter
    assert 'context.slot(model.children, "drawer")?.invoke()' in adapter
    assert "content = { context.children(model.children) }" in adapter


def test_a_gated_family_composes_its_component_from_the_holder() -> None:
    """A sheet shows itself once composed, so presence is the host's decision."""
    adapter = render(GATED, components()[GATED])
    assert (
        "val sheetStateValue = context.sheetState("
        "model.props.open, model.props.onOpenChange)" in adapter
    )
    assert "if (sheetStateValue.visible) {" in adapter
    assert "sheetState = sheetStateValue.state" in adapter
    # The component has already hidden itself when it calls this, and the
    # settled change reports through the report prop, so nothing answers it.
    assert "onDismissRequest = {}" in adapter
    assert "open =" not in adapter
    assert "onOpenChange =" not in adapter
    assert 'dragHandle = context.slot(model.children, "dragHandle")' in adapter
    assert "content = { context.children(model.children) }" in adapter


def test_the_holder_stays_outside_the_gate() -> None:
    """The state must outlive the composition of the component it projects."""
    adapter = render(GATED, components()[GATED])
    holder = adapter.index("val sheetStateValue = context.sheetState(")
    gate = adapter.index("if (sheetStateValue.visible) {")
    assert holder < gate


def test_a_component_without_a_holder_gets_no_state_local() -> None:
    """Only components that declare a holder ask the renderer for one."""
    adapter = render("Column", components()["Column"])
    assert "context.drawerState(" not in adapter


def test_every_state_kind_has_a_holder_and_a_gate_decision() -> None:
    """A family without a renderer method or a gate decision cannot be emitted."""
    from pycompose.core.registry_types import STATE_KINDS
    from pycompose.schema.codegen.adapters import GATED_STATES, STATE_CALLS

    assert set(STATE_CALLS) == set(STATE_KINDS)
    assert set(STATE_KINDS) >= GATED_STATES


# ---------------------------------------------------------------------------
# The codegen refuses a state it cannot render faithfully
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


def _state(registry: dict[str, Any], component: str = STATEFUL) -> dict[str, Any]:
    """Return one mutably loaded state entry.

    Args:
        registry: The loaded catalog.
        component: Component owning the state.

    Returns:
        The state's raw entry, for the caller to break.
    """
    return registry["components"][component]["state"]


def _payload(registry: dict[str, Any], prop: str, component: str = STATEFUL) -> dict:
    """Return one reported prop's payload field.

    Args:
        registry: The loaded catalog.
        prop: The reporting prop whose payload to break.
        component: Component owning the prop.

    Returns:
        The payload field, for the caller to break.
    """
    return registry["components"][component]["props"][prop]["payload"][0]


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda registry: registry["components"][STATEFUL].update(state=3),
            "must be an object",
        ),
        (
            lambda registry: _state(registry).update(unknown=True),
            "unknown keys",
        ),
        (
            lambda registry: _state(registry).update(kind="dialog"),
            "unknown state kind",
        ),
        (
            lambda registry: _state(registry).update(native="open"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(native="drawerContent"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(native="content"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss="open"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss="drawerState"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss="drawerContent"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss=3),
            "must be a parameter name",
        ),
        (
            lambda registry: _state(registry).update(value="onOpenChange"),
            "must be a boolean",
        ),
        (
            lambda registry: _state(registry).update(value="missing"),
            "must name one of the props",
        ),
        (
            lambda registry: _state(registry).update(report="open"),
            "must be an actionId",
        ),
        (
            lambda registry: _state(registry).update(report="missing"),
            "must name one of the props",
        ),
        (
            lambda registry: _payload(registry, "onOpenChange").update(type="string"),
            "needs one boolean payload field",
        ),
        (
            lambda registry: _payload(registry, "onOpenChange").update(name="Value"),
            "needs one boolean payload field",
        ),
    ],
)
def test_the_codegen_refuses_an_unrenderable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_it: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """A state the generator cannot drive faithfully is refused, not guessed.

    An adapter emitted from a half-understood declaration compiles and then
    drives the wrong value or reports none at all, which is worse than not
    building at all.
    """
    with pytest.raises(SystemExit, match=expected):
        _load_with(tmp_path, monkeypatch, break_it)


def test_the_codegen_refuses_a_second_reported_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One boolean is the whole report; two fields would mean the host guesses."""
    with pytest.raises(SystemExit, match="needs one boolean payload field"):
        _load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"][STATEFUL]["props"]["onOpenChange"][
                "payload"
            ].append({"name": "extra", "type": "boolean"}),
        )


# ---------------------------------------------------------------------------
# The runtime registry carries the declaration, not just the codegen
# ---------------------------------------------------------------------------


def test_the_runtime_registry_round_trips_the_state() -> None:
    """The registry type keeps the declaration a schema reader can trust."""
    from pycompose.core.registry_types import ComponentSpec
    from pycompose.errors import ComponentRegistryError

    state = {
        "native": "drawerState",
        "kind": "drawer",
        "value": "open",
        "report": "onOpenChange",
    }
    spec = ComponentSpec.from_mapping(
        STATEFUL,
        {
            "category": "layout",
            "stability": "stable",
            "props": {},
            "children": {"allowed": True},
            "state": state,
        },
    )
    assert spec.state is not None
    assert spec.state.kind == "drawer"
    assert spec.to_mapping()["state"] == state
    dismissed = {**state, "dismiss": "onDismissRequest"}
    spec = ComponentSpec.from_mapping(
        STATEFUL,
        {
            "category": "layout",
            "stability": "stable",
            "props": {},
            "children": {"allowed": True},
            "state": dismissed,
        },
    )
    assert spec.state is not None
    assert spec.state.dismiss == "onDismissRequest"
    assert spec.to_mapping()["state"] == dismissed
    with pytest.raises(ComponentRegistryError, match="'dismiss' must be a name"):
        ComponentSpec.from_mapping(
            STATEFUL,
            {
                "category": "layout",
                "stability": "stable",
                "props": {},
                "children": {"allowed": True},
                "state": {**state, "dismiss": 3},
            },
        )
    with pytest.raises(ComponentRegistryError, match="unknown state kind"):
        ComponentSpec.from_mapping(
            STATEFUL,
            {
                "category": "layout",
                "stability": "stable",
                "props": {},
                "children": {"allowed": True},
                "state": {**state, "kind": "dialog"},
            },
        )
    with pytest.raises(ComponentRegistryError, match="'native' must be a name"):
        ComponentSpec.from_mapping(
            STATEFUL,
            {
                "category": "layout",
                "stability": "stable",
                "props": {},
                "children": {"allowed": True},
                "state": {"native": 3},
            },
        )
